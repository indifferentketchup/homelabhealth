"""Smart bootstrap: bring the entire homelabhealth stack up from one container.

Run on orchestra startup. Detects first-run vs restart, creates networks,
volumes, pulls images, generates secrets, and starts containers in
dependency order. Idempotent.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import sys
import time
from typing import Any

import docker
from docker.errors import APIError, ImageNotFound, NotFound

logger = logging.getLogger("bootstrap")

REGISTRY = os.environ.get("HLH_REGISTRY", "ghcr.io/indifferentketchup")
VERSION = os.environ.get("HLH_VERSION", "latest")

PORT_API = os.environ.get("HLH_PORT_API", "9600")
PORT_UI = os.environ.get("HLH_PORT_UI", "9604")
PORT_SEARCH = os.environ.get("HLH_PORT_SEARCH", "9612")
PORT_CHAT = os.environ.get("HLH_CHAT_PORT", "9610")
CHAT_MEM = os.environ.get("HLH_CHAT_MEM", "7g")
MODELS_MAX = os.environ.get("HLH_MODELS_MAX", "2")

NETWORK_DEFAULT = "hlh_default"
NETWORK_INFERENCE = "hlh_inference"

VOLUMES = [
    "hlh_db_data", "hlh_keys", "hlh_uploads", "hlh_branding",
    "hlh_history", "hlh_models", "hlh_config", "hlh_vision_cache",
]

CONFIG_VOLUME = "hlh_config"
CONFIG_MOUNT = "/data/config"
SECRETS_FILE = f"{CONFIG_MOUNT}/secrets.env"

# CPU image by default; GPU image picked at bootstrap time if nvidia available
CHAT_IMAGE_CPU = os.environ.get("HLH_CHAT_IMAGE_CPU", "ghcr.io/ggml-org/llama.cpp:server-b9282")
CHAT_IMAGE_GPU = os.environ.get("HLH_CHAT_IMAGE_GPU", "ghcr.io/ggml-org/llama.cpp:server-cuda-b9282")

DB_IMAGE = "pgvector/pgvector:pg16"
SEARCH_IMAGE = "searxng/searxng:2026.5.22-c57f772ad"
INFINITY_IMAGE = os.environ.get("HLH_INFER_IMAGE", "michaelf34/infinity:0.0.77-cpu")
MEDSIGLIP_MODEL = os.environ.get("HLH_MEDSIGLIP_MODEL", "indifferentketchup/medsiglip-448-fp16")

# Bind-mounted config templates live inside the orchestra image; on first run
# we copy them into hlh_config volume so other containers can read them.
TEMPLATE_DIR = "/app/templates"
MODELS_INI_TEMPLATE = f"{TEMPLATE_DIR}/models.ini"
SEARXNG_YML_TEMPLATE = f"{TEMPLATE_DIR}/searxng_settings.yml"

# Where templates land in the hlh_config volume
MODELS_INI_PATH = f"{CONFIG_MOUNT}/models.ini"
SEARXNG_YML_PATH = f"{CONFIG_MOUNT}/searxng_settings.yml"


# ── Logging ──────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    """Print bootstrap step to stdout (visible in `docker logs`)."""
    print(f"[bootstrap] {msg}", flush=True)


def fail(msg: str, exit_code: int = 1) -> None:
    print(f"[bootstrap] FATAL: {msg}", file=sys.stderr, flush=True)
    sys.exit(exit_code)


# ── GPU detection ─────────────────────────────────────────────────────────────

def _gpu_probe_ok(client: docker.DockerClient) -> bool:
    """Last-resort GPU check: actually launch a probe container with a GPU.

    Docker Desktop (common on WSL) exposes GPUs via device requests WITHOUT
    registering a runtime named "nvidia", so the Runtimes check misses it.
    Reuse the api image (pulled regardless) as the probe — the NVIDIA toolkit
    injects nvidia-smi into any container granted a GPU. nvidia-smi -L exits
    non-zero (→ ContainerError) when no GPU is actually usable.
    """
    image = f"{REGISTRY}/hlh_api:{VERSION}"
    try:
        pull_image(client, image)
        client.containers.run(
            image,
            entrypoint=["nvidia-smi"],
            command=["-L"],
            device_requests=[docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])],
            remove=True,
            network_mode="none",
        )
        return True
    except Exception as e:  # APIError / ContainerError / ImageNotFound / ...
        log(f"GPU probe negative ({type(e).__name__})")
        return False


def detect_gpu(client: docker.DockerClient) -> bool:
    """Return True if Docker can pass an NVIDIA GPU into containers.

    Fast path: the daemon advertises an "nvidia" runtime (native docker +
    NVIDIA Container Toolkit). Fallback: actually run a probe container with a
    GPU device request — covers Docker Desktop / WSL, which exposes GPUs
    without a named runtime even when `nvidia-smi` works on the host.
    """
    try:
        info = client.info()
        runtimes = info.get("Runtimes", {})
        if "nvidia" in runtimes:
            return True
    except APIError:
        pass
    return _gpu_probe_ok(client)


# ── Secrets ──────────────────────────────────────────────────────────────────

def _gen_master_key() -> str:
    """64 random bytes, base64-encoded — same format as services/key_manager.py."""
    return base64.b64encode(secrets.token_bytes(64)).decode("ascii")


def _gen_token() -> str:
    return secrets.token_urlsafe(32)


def ensure_secrets(client: docker.DockerClient) -> dict[str, str]:
    """Read existing secrets from hlh_config volume, or generate on first run.

    Runs a throwaway alpine container with hlh_config mounted; reads or writes
    /data/config/secrets.env. This is the only way to interact with a named
    volume from the orchestra container itself.
    """
    # Try to read existing
    try:
        result = client.containers.run(
            "alpine:3.20",
            command=["sh", "-c", f"cat {SECRETS_FILE} 2>/dev/null || true"],
            volumes={CONFIG_VOLUME: {"bind": CONFIG_MOUNT, "mode": "rw"}},
            remove=True,
            stdout=True,
            stderr=False,
        )
        existing = result.decode("utf-8").strip() if result else ""
    except Exception:
        existing = ""

    if existing:
        # Parse KEY=VALUE lines
        parsed: dict[str, str] = {}
        for line in existing.splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip()
        if "HLH_MASTER_KEY" in parsed and "ORCHESTRA_TOKEN" in parsed:
            log("secrets: loaded existing")
            return parsed

    # First run — generate
    log("secrets: generating new HLH_MASTER_KEY and ORCHESTRA_TOKEN")
    secrets_dict = {
        "HLH_MASTER_KEY": _gen_master_key(),
        "ORCHESTRA_TOKEN": _gen_token(),
    }
    content = "\n".join(f"{k}={v}" for k, v in secrets_dict.items()) + "\n"
    # Write atomically via heredoc; ensure config dir exists
    write_cmd = (
        f"mkdir -p {CONFIG_MOUNT} && "
        f"cat > {SECRETS_FILE}.tmp <<'EOF'\n{content}EOF\n"
        f"mv {SECRETS_FILE}.tmp {SECRETS_FILE} && "
        f"chmod 600 {SECRETS_FILE}"
    )
    client.containers.run(
        "alpine:3.20",
        command=["sh", "-c", write_cmd],
        volumes={CONFIG_VOLUME: {"bind": CONFIG_MOUNT, "mode": "rw"}},
        remove=True,
    )
    return secrets_dict


def write_templates(client: docker.DockerClient) -> None:
    """Copy models.ini and searxng_settings.yml from the orchestra image into hlh_config."""
    with open(MODELS_INI_TEMPLATE, "r") as f:
        models_ini = f.read()
    with open(SEARXNG_YML_TEMPLATE, "r") as f:
        searxng_yml = f.read()

    # Heredoc with sentinel that won't collide with file content
    cmd = (
        f"mkdir -p {CONFIG_MOUNT} && "
        f"cat > {MODELS_INI_PATH} <<'HLH_EOF_MODELS'\n{models_ini}\nHLH_EOF_MODELS\n"
        f"cat > {SEARXNG_YML_PATH} <<'HLH_EOF_SEARXNG'\n{searxng_yml}\nHLH_EOF_SEARXNG\n"
    )
    client.containers.run(
        "alpine:3.20",
        command=["sh", "-c", cmd],
        volumes={CONFIG_VOLUME: {"bind": CONFIG_MOUNT, "mode": "rw"}},
        remove=True,
    )


# ── Networks & volumes ───────────────────────────────────────────────────────

def ensure_network(client: docker.DockerClient, name: str, internal: bool = False) -> None:
    try:
        client.networks.get(name)
    except NotFound:
        log(f"creating network {name}{' (internal)' if internal else ''}")
        client.networks.create(name, driver="bridge", internal=internal)


def ensure_volume(client: docker.DockerClient, name: str) -> None:
    try:
        client.volumes.get(name)
    except NotFound:
        log(f"creating volume {name}")
        client.volumes.create(name)


# ── Image pulls ──────────────────────────────────────────────────────────────

def pull_image(client: docker.DockerClient, image: str) -> None:
    """Pull image if not already present locally."""
    try:
        client.images.get(image)
        return  # already present
    except ImageNotFound:
        pass

    log(f"pulling {image}...")
    last_err = None
    for attempt in range(3):
        try:
            client.images.pull(image)
            return
        except APIError as e:
            last_err = e
            log(f"  pull attempt {attempt + 1}/3 failed: {e}")
            time.sleep(2 ** attempt)
    fail(f"failed to pull {image} after 3 attempts: {last_err}")


# ── Container creation ───────────────────────────────────────────────────────

COMMON_HARDENING: dict[str, Any] = {
    "read_only": True,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
}


def container_exists(client: docker.DockerClient, name: str) -> bool:
    try:
        client.containers.get(name)
        return True
    except NotFound:
        return False


def ensure_container(client: docker.DockerClient, name: str, create_fn) -> Any:
    """Get existing container by name, or create via create_fn. Start if not running."""
    try:
        c = client.containers.get(name)
        if c.status != "running":
            log(f"starting existing {name}")
            c.start()
        return c
    except NotFound:
        log(f"creating {name}")
        c = create_fn()
        c.start()
        return c


def wait_for_healthy(client: docker.DockerClient, name: str, timeout_s: int = 60) -> None:
    """Block until container reports healthy. Falls back to running-status if no healthcheck."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            c = client.containers.get(name)
            c.reload()
            health = c.attrs.get("State", {}).get("Health", {})
            status = health.get("Status")
            if status == "healthy":
                return
            if status is None and c.status == "running":
                # No healthcheck defined — assume ok once running
                time.sleep(2)
                return
            time.sleep(1)
        except NotFound:
            time.sleep(1)
    fail(f"{name} did not become healthy within {timeout_s}s")


def create_db(client: docker.DockerClient) -> Any:
    return client.containers.create(
        image=DB_IMAGE,
        name="hlh_db",
        restart_policy={"Name": "unless-stopped"},
        environment={
            "POSTGRES_USER": "hlh",
            "POSTGRES_PASSWORD": "hlh",
            "POSTGRES_DB": "hlh",
        },
        volumes={"hlh_db_data": {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        network=NETWORK_DEFAULT,
        tmpfs={"/tmp": "", "/run/postgresql": ""},
        read_only=True,
        cap_drop=["ALL"],
        cap_add=["CHOWN", "FOWNER", "DAC_OVERRIDE", "SETUID", "SETGID"],
        security_opt=["no-new-privileges:true"],
        healthcheck={
            "test": ["CMD-SHELL", "pg_isready -U hlh -d hlh"],
            "interval": 5_000_000_000,  # ns
            "timeout": 5_000_000_000,
            "retries": 5,
        },
    )


def create_api(
    client: docker.DockerClient, master_key: str, orch_token: str, gpu: bool = False
) -> Any:
    image = f"{REGISTRY}/hlh_api:{VERSION}"
    extra: dict[str, Any] = {}
    if gpu:
        # GPU visibility so in-container hardware detection (nvidia-smi) can
        # report VRAM, which drives the tier picker's GPU-tier recommendation.
        extra["device_requests"] = [
            docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])
        ]
    return client.containers.create(
        image=image,
        name="hlh_api",
        restart_policy={"Name": "unless-stopped"},
        environment={
            "DATABASE_URL": "postgresql://hlh:hlh@hlh_db:5432/hlh",
            "SEARXNG_URL": "http://hlh_search:8080",
            "HLH_MASTER_KEY": master_key,
            "ORCHESTRA_TOKEN": orch_token,
        },
        ports={"8000/tcp": int(PORT_API)},
        volumes={
            "hlh_keys": {"bind": "/data/keys", "mode": "rw"},
            "hlh_uploads": {"bind": "/data/uploads", "mode": "rw"},
            "hlh_branding": {"bind": "/data/branding", "mode": "rw"},
            "hlh_history": {"bind": "/data/history", "mode": "rw"},
            "hlh_models": {"bind": "/models", "mode": "rw"},
        },
        network=NETWORK_DEFAULT,
        user="1000:1000",
        tmpfs={"/tmp": ""},
        **extra,
        **COMMON_HARDENING,
    )


def create_chat(client: docker.DockerClient, image: str, gpu: bool) -> Any:
    extra: dict[str, Any] = {}
    if gpu:
        extra["device_requests"] = [
            docker.types.DeviceRequest(count=1, capabilities=[["gpu"]])
        ]
    return client.containers.create(
        image=image,
        name="hlh_chat",
        restart_policy={"Name": "unless-stopped"},
        environment={"LD_LIBRARY_PATH": "/app"},
        volumes={
            "hlh_models": {"bind": "/models", "mode": "ro"},
            CONFIG_VOLUME: {"bind": "/config", "mode": "ro"},
        },
        command=[
            "--models-preset", "/config/models.ini",
            "--host", "0.0.0.0",
            "--port", PORT_CHAT,
            "--models-max", MODELS_MAX,
        ],
        network=NETWORK_INFERENCE,
        user="1000:1000",
        tmpfs={"/tmp": ""},
        mem_limit=CHAT_MEM,
        healthcheck={
            "test": ["CMD-SHELL", f"curl -fsS http://localhost:{PORT_CHAT}/v1/models || exit 1"],
            "interval": 30_000_000_000,
            "timeout": 5_000_000_000,
            "retries": 3,
            "start_period": 60_000_000_000,
        },
        **COMMON_HARDENING,
        **extra,
    )


def create_search(client: docker.DockerClient) -> Any:
    return client.containers.create(
        image=SEARCH_IMAGE,
        name="hlh_search",
        restart_policy={"Name": "unless-stopped"},
        environment={
            "SEARXNG_SECRET_KEY": "homelabhealth-bundled-search",
            "SEARXNG_BASE_URL": "http://hlh_search:8080/",
        },
        ports={"8080/tcp": int(PORT_SEARCH)},
        volumes={
            CONFIG_VOLUME: {"bind": "/etc/searxng_template", "mode": "ro"},
        },
        # Use entrypoint shim: copy template into /etc/searxng (writable tmpfs)
        # before SearXNG starts. SearXNG needs settings at /etc/searxng/settings.yml.
        # We can't bind-mount a single file into tmpfs, so we pre-stage.
        # Use the image's own /docker-entrypoint.sh by passing nothing.
        command=None,
        network=NETWORK_DEFAULT,
        user="1000:1000",
        tmpfs={"/tmp": "", "/etc/searxng": ""},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        read_only=True,
        healthcheck={
            "test": ["CMD-SHELL", "wget -qO- http://localhost:8080/healthz || exit 1"],
            "interval": 30_000_000_000,
            "timeout": 5_000_000_000,
            "retries": 3,
            "start_period": 30_000_000_000,
        },
    )


def create_ui(client: docker.DockerClient) -> Any:
    image = f"{REGISTRY}/hlh_ui:{VERSION}"
    return client.containers.create(
        image=image,
        name="hlh_ui",
        restart_policy={"Name": "unless-stopped"},
        environment={"HLH_API_UPSTREAM": "hlh_api:8000"},
        ports={"80/tcp": int(PORT_UI)},
        network=NETWORK_DEFAULT,
        tmpfs={
            "/tmp": "",
            "/var/cache/nginx": "",
            "/run": "",
            "/etc/nginx/conf.d": "",
        },
        read_only=True,
        cap_drop=["ALL"],
        cap_add=["NET_BIND_SERVICE", "SETUID", "SETGID", "CHOWN"],
        security_opt=["no-new-privileges:true"],
    )


def attach_to_network(client: docker.DockerClient, container_name: str, network_name: str) -> None:
    """Attach a container to an additional network (idempotent)."""
    try:
        net = client.networks.get(network_name)
        net.reload()
        attached = [c.name for c in net.containers]
        if container_name not in attached:
            net.connect(container_name)
    except NotFound:
        pass


# ── Searxng config bootstrap ─────────────────────────────────────────────────

def stage_searxng_config(client: docker.DockerClient) -> None:
    """Copy settings.yml into /etc/searxng inside the hlh_search container.

    Done after creation because we can't bind-mount a file into a tmpfs
    directory. The image starts with /etc/searxng template files; we drop
    our settings.yml on top before SearXNG initializes.
    """
    # Read the template from inside the orchestra container
    with open(SEARXNG_YML_TEMPLATE, "r") as f:
        content = f.read()
    # Write via docker exec
    c = client.containers.get("hlh_search")
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    c.exec_run(
        ["sh", "-c", f"echo '{encoded}' | base64 -d > /etc/searxng/settings.yml"],
        user="root",
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def run() -> dict[str, str]:
    """Bootstrap entry point. Returns dict of generated secrets for the caller."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [bootstrap] %(message)s",
    )

    log("checking docker socket...")
    try:
        client = docker.from_env()
        client.ping()
    except Exception as e:
        fail(f"docker socket unreachable: {e}\n  hint: mount /var/run/docker.sock into this container")

    first_run = not container_exists(client, "hlh_db")
    log("first run detected" if first_run else "existing stack detected, restart path")

    gpu = detect_gpu(client)
    chat_image = CHAT_IMAGE_GPU if gpu else CHAT_IMAGE_CPU
    log(f"GPU: {'detected' if gpu else 'none, using CPU images'}")

    ensure_network(client, NETWORK_DEFAULT, internal=False)
    ensure_network(client, NETWORK_INFERENCE, internal=True)

    for vol in VOLUMES:
        ensure_volume(client, vol)

    # Pull images upfront so we have a clear progress phase
    pull_image(client, "alpine:3.20")  # used by secrets/template helpers
    pull_image(client, DB_IMAGE)
    pull_image(client, f"{REGISTRY}/hlh_api:{VERSION}")
    pull_image(client, chat_image)
    pull_image(client, SEARCH_IMAGE)
    pull_image(client, f"{REGISTRY}/hlh_ui:{VERSION}")
    pull_image(client, INFINITY_IMAGE)

    secrets_dict = ensure_secrets(client)
    write_templates(client)

    # Start in dependency order
    ensure_container(client, "hlh_db", lambda: create_db(client))
    wait_for_healthy(client, "hlh_db", timeout_s=90)

    api = ensure_container(
        client, "hlh_api",
        lambda: create_api(client, secrets_dict["HLH_MASTER_KEY"], secrets_dict["ORCHESTRA_TOKEN"], gpu=gpu),
    )
    # hlh_api needs to be on both networks
    attach_to_network(client, "hlh_api", NETWORK_INFERENCE)
    wait_for_healthy(client, "hlh_api", timeout_s=60)

    ensure_container(client, "hlh_chat", lambda: create_chat(client, chat_image, gpu))
    ensure_container(client, "hlh_search", lambda: create_search(client))
    # Stage searxng config after start (can't bind-mount file into tmpfs)
    try:
        stage_searxng_config(client)
    except Exception as e:
        log(f"warn: searxng config stage failed: {e}")

    ensure_container(client, "hlh_ui", lambda: create_ui(client))

    log(f"done — homelabhealth is running → http://localhost:{PORT_UI}")
    return secrets_dict


if __name__ == "__main__":
    run()
