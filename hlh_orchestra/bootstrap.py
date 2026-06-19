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
# Inference front-door memory budget (mirrors docker-compose.yml HLH_INFER_MEM).
INFER_MEM = os.environ.get("HLH_INFER_MEM", "4g")

NETWORK_DEFAULT = "hlh_default"
NETWORK_INFERENCE = "hlh_inference"

VOLUMES = [
    "hlh_db_data", "hlh_keys", "hlh_uploads", "hlh_branding",
    "hlh_history", "hlh_models", "hlh_config", "hlh_infer_cache",
]

CONFIG_VOLUME = "hlh_config"
CONFIG_MOUNT = "/data/config"
SECRETS_FILE = f"{CONFIG_MOUNT}/secrets.env"

# Inference front-door image (llama-swap + boofinity). A single HLH_SWAP_IMAGE
# override mirrors docker-compose.yml; otherwise CPU/CUDA defaults are picked by
# GPU detection at bootstrap time.
SWAP_IMAGE_CPU = os.environ.get("HLH_SWAP_IMAGE", "ghcr.io/indifferentketchup/hlh-swap:0.1.0-cpu")
SWAP_IMAGE_GPU = os.environ.get("HLH_SWAP_IMAGE", "ghcr.io/indifferentketchup/hlh-swap:0.1.0-cuda")

DB_IMAGE = "pgvector/pgvector:pg16"
SEARCH_IMAGE = "searxng/searxng:2026.5.22-c57f772ad"

# Bind-mounted config templates live inside the orchestra image; on first run
# we copy them into hlh_config volume so other containers can read them.
TEMPLATE_DIR = "/app/templates"
MODELS_INI_TEMPLATE = f"{TEMPLATE_DIR}/models.ini"
SEARXNG_YML_TEMPLATE = f"{TEMPLATE_DIR}/searxng_settings.yml"
SWAP_CONFIG_TEMPLATE = f"{TEMPLATE_DIR}/swap_config.yaml"

# Where templates land in the hlh_config volume
MODELS_INI_PATH = f"{CONFIG_MOUNT}/models.ini"
SEARXNG_YML_PATH = f"{CONFIG_MOUNT}/searxng_settings.yml"
SWAP_CONFIG_PATH = f"{CONFIG_MOUNT}/swap_config.yaml"


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
    Reuse the api image (pulled regardless) as the probe  -  the NVIDIA toolkit
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
    GPU device request  -  covers Docker Desktop / WSL, which exposes GPUs
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
    """64 random bytes, base64-encoded  -  same format as services/key_manager.py."""
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

    # First run  -  generate
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
    """Copy models.ini, searxng_settings.yml, and swap_config.yaml into hlh_config."""
    with open(MODELS_INI_TEMPLATE, "r") as f:
        models_ini = f.read()
    with open(SEARXNG_YML_TEMPLATE, "r") as f:
        searxng_yml = f.read()
    with open(SWAP_CONFIG_TEMPLATE, "r") as f:
        swap_config = f.read()

    # Heredoc with sentinel that won't collide with file content
    cmd = (
        f"mkdir -p {CONFIG_MOUNT} && "
        f"cat > {MODELS_INI_PATH} <<'HLH_EOF_MODELS'\n{models_ini}\nHLH_EOF_MODELS\n"
        f"cat > {SEARXNG_YML_PATH} <<'HLH_EOF_SEARXNG'\n{searxng_yml}\nHLH_EOF_SEARXNG\n"
        f"cat > {SWAP_CONFIG_PATH} <<'HLH_EOF_SWAP'\n{swap_config}\nHLH_EOF_SWAP\n"
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


def ensure_models_ownership(client: docker.DockerClient) -> None:
    """Make the hlh_models volume writable by the uid-1000 containers.

    Docker only chowns a *fresh empty* named volume to the first mounting
    user; once anything has populated it (a root helper, a prior run), the
    root stays root-owned and the read_only uid-1000 hlh_api can't create
    flat /models/<file> downloads (embed/rerank/tasks/chat land there)  - 
    they fail with EACCES. A throwaway root container fixes ownership
    idempotently; recursive so re-running the installer self-heals an
    already-broken volume. chown is metadata-only, so it's fast even with
    multi-GB GGUFs present.
    """
    try:
        client.containers.run(
            "alpine:3.20",
            command=["chown", "-R", "1000:1000", "/models"],
            volumes={"hlh_models": {"bind": "/models", "mode": "rw"}},
            remove=True,
        )
        log("models volume ownership ensured (1000:1000)")
    except APIError as exc:
        log(f"WARN: could not chown hlh_models volume: {exc}")


def ensure_infer_cache_ownership(client: docker.DockerClient) -> None:
    """Make the hlh_infer_cache volume writable by the uid-1000 hlh_api.

    Same failure class as hlh_models (see ensure_models_ownership): once the HF
    hub cache volume is populated it can stay root-owned, and the read_only
    uid-1000 hlh_api then EACCES on snapshot_download writes under /cache/hub.
    A throwaway root container chowns it idempotently; recursive so a re-run
    self-heals an already-broken volume.
    """
    try:
        client.containers.run(
            "alpine:3.20",
            command=["chown", "-R", "1000:1000", "/cache"],
            volumes={"hlh_infer_cache": {"bind": "/cache", "mode": "rw"}},
            remove=True,
        )
        log("infer cache volume ownership ensured (1000:1000)")
    except APIError as exc:
        log(f"WARN: could not chown hlh_infer_cache volume: {exc}")


# ── Image pulls ──────────────────────────────────────────────────────────────

def pull_image(client: docker.DockerClient, image: str) -> None:
    """Always pull so floating tags (our :latest images) actually refresh.

    The old behaviour was skip-if-present, which meant `:latest` was pulled once
    and then NEVER updated  -  so re-running the bootstrap (e.g. via hlhupdate)
    recreated containers from a stale local image and silently shipped old code.
    We now always pull; pinned tags are a cheap no-op (cached layers), floating
    tags refresh. If the registry is unreachable but a local copy exists, fall
    back to it instead of failing (lets offline restarts still work).
    """
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

    # Pull failed  -  use a local copy if we have one, otherwise give up.
    try:
        client.images.get(image)
        log(f"  registry unreachable; using local {image} ({last_err})")
        return
    except ImageNotFound:
        pass
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


def _container_image_drifted(client: docker.DockerClient, c: Any, image: str) -> bool:
    """True when the existing container was built from a different image than the
    freshly-pulled target. pull_image runs before ensure_container, so a mismatch
    means an update landed new code (and any compose-parity changes baked into the
    bootstrap, e.g. a new volume mount) that the running container predates."""
    try:
        return c.image.id != client.images.get(image).id
    except (ImageNotFound, APIError) as exc:
        log(f"WARN: could not compare {c.name} image to {image}, not recreating: {exc}")
        return False


def ensure_container(
    client: docker.DockerClient, name: str, create_fn, image: str | None = None
) -> Any:
    """Get existing container by name, or create via create_fn. Start if not running.

    When `image` is given and the existing container's image has drifted from the
    freshly-pulled target, the container is removed and recreated so config changes
    (mounts, env, command) baked into create_fn actually take effect on update."""
    try:
        c = client.containers.get(name)
        if image is not None and _container_image_drifted(client, c, image):
            log(f"recreating {name}: image drifted from {image}")
            c.remove(force=True)
            c = create_fn()
            c.start()
            return c
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
                # No healthcheck defined  -  assume ok once running
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
            "HLH_VERSION": VERSION,  # surfaced in the startup banner
        },
        ports={"8000/tcp": int(PORT_API)},
        volumes={
            "hlh_keys": {"bind": "/data/keys", "mode": "rw"},
            "hlh_uploads": {"bind": "/data/uploads", "mode": "rw"},
            "hlh_branding": {"bind": "/data/branding", "mode": "rw"},
            "hlh_history": {"bind": "/data/history", "mode": "rw"},
            "hlh_models": {"bind": "/models", "mode": "rw"},
            # model_puller writes the boofinity HF snapshot (embed/rerank
            # safetensors) here; hlh_swap reads it as HF_HOME=/cache. Without this
            # mount /cache is the read_only container root and snapshot_download
            # fails with EROFS. Mirrors docker-compose.yml hlh_api.
            "hlh_infer_cache": {"bind": "/cache", "mode": "rw"},
        },
        network=NETWORK_DEFAULT,
        user="1000:1000",
        tmpfs={"/tmp": ""},
        **extra,
        **COMMON_HARDENING,
    )


def create_swap(client: docker.DockerClient, image: str, gpu: bool) -> Any:
    """Inference front-door (llama-swap + boofinity children), port 9620.

    Mirrors the docker-compose.yml hlh_swap_cpu/gpu service. The Docker SDK cannot
    express compose's `env_file:` or single-file bind mount, so: the explicit env
    block below stands in for env_file (HLH_INFER_DEVICE is set for gpu; the rest of
    HLH_INFER_* default in config.yaml macros), and the llama-swap config is consumed
    from the hlh_config volume at /config/swap_config.yaml (write_templates already
    stages it from the orchestra swap_config.yaml template), rather than a host bind of
    the single file.
    """
    extra: dict[str, Any] = {}
    environment = {
        "HF_HOME": "/cache",
        "HOME": "/cache",
        "HF_HUB_OFFLINE": "1",
        "LD_LIBRARY_PATH": "/app",
    }
    if gpu:
        environment["HLH_INFER_DEVICE"] = "cuda"
        extra["device_requests"] = [
            docker.types.DeviceRequest(count=1, capabilities=[["gpu"]])
        ]
    return client.containers.create(
        image=image,
        name="hlh_swap",
        restart_policy={"Name": "unless-stopped"},
        environment=environment,
        volumes={
            "hlh_models": {"bind": "/models", "mode": "ro"},
            "hlh_infer_cache": {"bind": "/cache", "mode": "rw"},
            CONFIG_VOLUME: {"bind": "/config", "mode": "ro"},
        },
        command=[
            "--config", "/config/swap_config.yaml",
            "--listen", "0.0.0.0:9620",
        ],
        network=NETWORK_INFERENCE,
        user="1000:1000",
        tmpfs={"/tmp": "", "/run": ""},
        mem_limit=INFER_MEM,
        healthcheck={
            "test": [
                "CMD-SHELL",
                "python -c \"import urllib.request,sys; "
                "sys.exit(0 if urllib.request.urlopen('http://localhost:9620/v1/models').status==200 else 1)\" "
                "|| exit 1",
            ],
            "interval": 30_000_000_000,
            "timeout": 5_000_000_000,
            "retries": 3,
            "start_period": 120_000_000_000,
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
        # Entrypoint shim. SearXNG's image entrypoint creates
        # /etc/searxng/settings.yml from its own template on boot, but
        # /etc/searxng is a root-owned tmpfs while the process runs as uid 1000,
        # so that write fails ("Permission denied") and the container restart-
        # loops. We make the tmpfs writable (mode=1777) and copy our staged
        # settings.yml in from the read-only hlh_config template mount before
        # handing off to the real entrypoint. Replaces the old post-start
        # `docker exec` injection, which raced SearXNG's startup and 409'd.
        entrypoint=[
            "/bin/sh",
            "-c",
            "cp /etc/searxng_template/searxng_settings.yml "
            "/etc/searxng/settings.yml && exec /usr/local/searxng/entrypoint.sh",
        ],
        network=NETWORK_DEFAULT,
        user="1000:1000",
        tmpfs={"/tmp": "mode=1777", "/etc/searxng": "mode=1777"},
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
    swap_image = SWAP_IMAGE_GPU if gpu else SWAP_IMAGE_CPU
    log(f"GPU: {'detected' if gpu else 'none, using CPU images'}")

    ensure_network(client, NETWORK_DEFAULT, internal=False)
    ensure_network(client, NETWORK_INFERENCE, internal=True)

    for vol in VOLUMES:
        ensure_volume(client, vol)

    # Pull images upfront so we have a clear progress phase
    pull_image(client, "alpine:3.20")  # used by secrets/template helpers
    pull_image(client, DB_IMAGE)
    pull_image(client, f"{REGISTRY}/hlh_api:{VERSION}")
    pull_image(client, swap_image)
    pull_image(client, SEARCH_IMAGE)
    pull_image(client, f"{REGISTRY}/hlh_ui:{VERSION}")

    # /models and /cache must be writable by the uid-1000 containers (alpine is
    # pulled above). hlh_infer_cache holds the boofinity HF snapshot the puller writes.
    ensure_models_ownership(client)
    ensure_infer_cache_ownership(client)

    secrets_dict = ensure_secrets(client)
    write_templates(client)

    # Start in dependency order
    ensure_container(client, "hlh_db", lambda: create_db(client), image=DB_IMAGE)
    wait_for_healthy(client, "hlh_db", timeout_s=90)

    api = ensure_container(
        client, "hlh_api",
        lambda: create_api(client, secrets_dict["HLH_MASTER_KEY"], secrets_dict["ORCHESTRA_TOKEN"], gpu=gpu),
        image=f"{REGISTRY}/hlh_api:{VERSION}",
    )
    # hlh_api needs to be on both networks
    attach_to_network(client, "hlh_api", NETWORK_INFERENCE)
    wait_for_healthy(client, "hlh_api", timeout_s=60)

    ensure_container(client, "hlh_swap", lambda: create_swap(client, swap_image, gpu), image=swap_image)
    ensure_container(client, "hlh_search", lambda: create_search(client), image=SEARCH_IMAGE)

    ensure_container(client, "hlh_ui", lambda: create_ui(client), image=f"{REGISTRY}/hlh_ui:{VERSION}")

    log(f"done  -  homelabhealth is running → http://localhost:{PORT_UI}")
    return secrets_dict


if __name__ == "__main__":
    run()
