# Design: boofinity-inference-frontdoor

**Date:** 2026-06-16

---

## Topology decision: one combined container, child-process backends

llama-swap can run either way:

1. **Child `cmd` processes** - one `hlh_swap` container whose entrypoint is
   `llama-swap` and whose model `cmd:` lines fork `llama-server` and `boofinity`
   as **child processes inside the same container**. This is the
   `/opt/boofinity/DEPLOY.md:93` "llama-swap child pattern".
2. **Sibling containers** - `hlh_chat` and `hlh_infer` stay as separate compose
   services; `hlh_swap`'s `cmd:` runs `docker start`/`docker stop` over the
   Docker socket to swap the two siblings.

**Chosen: child processes (option 1).** Adversarial review rejected option 2 for
three concrete reasons, each removed by option 1:

- **No `docker` CLI dependency.** The sibling design needs a `docker` client
  binary inside the `llama-swap:v226` minimal Go image to run `docker start -a
  ...`; that binary may be absent. The child pattern forks `llama-server` and
  `boofinity` binaries that live in the combined image, so no `docker` CLI is
  needed.
- **No Docker socket.** The sibling design mounts `/var/run/docker.sock` into
  `hlh_swap`, and `docker start`/`docker stop` are write operations on the daemon
  API, so the mount grants full Docker daemon control - a real
  privilege-escalation surface that a `:ro` bind does not scope down. The child
  pattern touches no socket at all.
- **No cold-start double-VRAM race.** With siblings, a cold `docker compose up`
  can start both `hlh_chat_gpu` and `hlh_infer_gpu`, both mapping the GPU before
  llama-swap has stopped either, OOM-ing. With children, llama-swap is the sole
  process that ever launches a backend; the swap-exclusive group guarantees only
  one child is resident at a time, in-process, with no compose race.

The trade-off accepted is a single combined image (larger than two minimal
images) and one shared container hardening profile rather than per-service
profiles. That is addressed in `## The combined image` below and listed as an
Open Risk (image size).

### llama-swap child config (v226 schema)

Each model's `cmd:` is the **launch command for a child process**; llama-swap
starts it, waits for the child's `/health`, then proxies requests to the child's
local port. `cmdStop` (or SIGTERM with grace) stops the child to free VRAM.

```yaml
# hlh_swap/config.yaml (v226 schema)
healthCheckTimeout: 120          # seconds to wait for a child /health (DEPLOY.md: 200 = ready)
startPort: 5800                  # base port llama-swap assigns to child processes

macros:
  # ${PORT} is substituted by llama-swap per child from startPort upward.
  llama_cmd: >-
    llama-server --models-preset /models/models.ini
    --host 127.0.0.1 --port ${PORT}
  boof_cmd: >-
    boofinity v2
    --model-id Qwen/Qwen3-Embedding-0.6B
    --model-id Qwen/Qwen3-Reranker-0.6B
    --device cpu
    --dtype ${HLH_INFER_DTYPE:-float32}
    --url-prefix /v1
    --host 127.0.0.1 --port ${PORT}

models:
  # --- llama-server child (chat / tasks / mmproj) ---
  medgemma:
    cmd: "${llama_cmd}"
    ttl: 600
    healthCheckTimeout: 120
  qwen-chat:
    cmd: "${llama_cmd}"
    ttl: 600
  gemma-tasks:
    cmd: "${llama_cmd}"
    ttl: 600

  # --- boofinity child (embed / rerank / VL) ---
  qwen3-embed:
    cmd: "${boof_cmd}"
    ttl: 300
  qwen3-reranker:
    cmd: "${boof_cmd}"
    ttl: 300
  qwen3-vl-embed:
    cmd: "${boof_cmd}"
    ttl: 300
  qwen3-vl-rerank:
    cmd: "${boof_cmd}"
    ttl: 300

groups:
  # The llama-server child and the boofinity child share one swap-exclusive
  # group: only one member runs at a time (swap: true), and running a member
  # unloads every other group's members too (exclusive: true). On a tight GPU
  # the llama.cpp child and the boofinity child are therefore never both
  # resident - this is enforced in-process by the group, not by a compose race.
  vram_constrained:
    swap: true
    exclusive: true
    members:
      - medgemma
      - qwen-chat
      - gemma-tasks
      - qwen3-embed
      - qwen3-reranker
      - qwen3-vl-embed
      - qwen3-vl-rerank
```

On the GPU build the `boof_cmd` macro additionally carries
`--device cuda`, `--model-id Qwen/Qwen3-VL-Embedding-2B`, and
`--model-id Qwen/Qwen3-VL-Reranker-2B`; the cpu build uses `--device cpu` and
omits the VL model ids (see `## docker-compose.yml changes`). The per-tier
command shape is supplied through the compose command / env, not by editing the
config per tier - the config file itself is static for v1.

Key semantics used (from the llama-swap v226 wiki; **the exact key names are an
Open Risk to confirm against the shipped v226 schema before merge**):

- `cmd` - the command llama-swap forks as a **child process**. The `${PORT}`
  macro is the local port llama-swap assigns the child and then proxies to.
- `ttl: <seconds>` - auto-unload (stop the child) after that many idle seconds
  (`> 0` to activate). Chat children carry a longer TTL (600s) than embed/rerank
  (300s) because chat is the interactive path.
- `healthCheckTimeout` - seconds to wait for the child's `/health` to return 200
  before routing. boofinity returns 200 on `/health` only after every model
  finishes loading (`DEPLOY.md` notes), so 120s accommodates first-load.
- `groups` with `swap: true` - only one member of the group runs at a time;
  requesting a member stops the others.
- `exclusive: true` - running a member of this group stops members in *all
  other* groups too.

`cmdStop` is left to the default SIGTERM-with-grace; `llama-server` and
`boofinity` both exit cleanly on SIGTERM, freeing their VRAM. No `cmdStop`
override is needed (and none would invoke `docker` - there is no socket).

### Two front-door config copies (sync rule)

- `hlh_swap/config.yaml` - mounted into the running `hlh_swap` container.
- `hlh_orchestra/templates/swap_config.yaml` - copied into the `hlh_config`
  volume by `bootstrap.py:write_templates` (alongside `models.ini` and
  `searxng_settings.yml`). Per CLAUDE.md, templates in
  `hlh_orchestra/templates/` must mirror the live config. The two files must be
  line-for-line identical.

---

## The combined image (`hlh_swap/Dockerfile`)

The combined image carries three binaries: `llama-swap` (entrypoint and process
manager), `llama-server` (chat/tasks/mmproj child), and `boofinity` (embed/
rerank/VL child). It is **FROM the boofinity image** (which already brings
python + torch + the boofinity install), then **COPYs** the `llama-server`
binary plus its shared libraries from the llama.cpp image and the `llama-swap`
binary from the llama-swap image. CPU and CUDA variants build FROM the matching
boofinity and llama.cpp bases.

```dockerfile
# hlh_swap/Dockerfile - multi-stage combined image (shape; cpu shown)
ARG BOOFINITY_BASE=ghcr.io/indifferentketchup/boofinity:0.1.0-cpu
ARG LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-b9660
ARG LLAMA_SWAP_IMAGE=ghcr.io/mostlygeek/llama-swap:v226

FROM ${LLAMA_CPP_IMAGE}  AS llamacpp
FROM ${LLAMA_SWAP_IMAGE} AS llamaswap

FROM ${BOOFINITY_BASE} AS final
# llama.cpp ships its shared libs in /app without ldconfig entries; carry them
# and point LD_LIBRARY_PATH at /app (CLAUDE.md read_only exception).
COPY --from=llamacpp  /app/llama-server  /usr/local/bin/llama-server
COPY --from=llamacpp  /app/*.so          /app/
COPY --from=llamaswap /app/llama-swap    /usr/local/bin/llama-swap
ENV LD_LIBRARY_PATH=/app \
    HOME=/cache \
    HF_HOME=/cache \
    HF_HUB_OFFLINE=1
ENTRYPOINT ["/usr/local/bin/llama-swap"]
```

The CUDA variant builds `ARG BOOFINITY_BASE=...:0.1.0-cuda` and
`ARG LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda-b9660`; everything
else is identical. The published tags are
`ghcr.io/indifferentketchup/hlh-swap:<ver>-cpu` and `...-cuda`, written into
`.env` as `HLH_SWAP_IMAGE` by `image_config.write_tier_env`.

This combined image **replaces** the standalone `hlh_chat` (llama.cpp) and
`hlh_infer` (boofinity) services: their work now runs as child processes of
`hlh_swap`. The exact COPY source paths (`/app/llama-server`, the `.so` set, the
`llama-swap` binary location) must be confirmed against the published b9660 and
v226 image layouts before the Dockerfile is finalized (a task verifies the
layout).

---

## docker-compose.yml changes

### `hlh_swap` (combined front-door, the single inference endpoint)

`hlh_swap` replaces both the `hlh_chat` and `hlh_infer` standalone services. It
is a CPU/GPU pair gated by `COMPOSE_PROFILES`.

```yaml
x-hlh-swap-base: &hlh-swap-base
  container_name: hlh_swap
  restart: unless-stopped
  env_file: [.env]
  environment:
    HF_HOME: /cache
    HOME: /cache
    HF_HUB_OFFLINE: "1"
    LD_LIBRARY_PATH: /app
  command: ["--config", "/config/config.yaml", "--listen", "0.0.0.0:9620"]
  volumes:
    - hlh_models:/models:ro                                # GGUFs + models.ini for the llama-server child
    - hlh_infer_cache:/cache                               # HF_HOME for the boofinity child
    - ./hlh_swap/config.yaml:/config/config.yaml:ro        # llama-swap child config
  user: "1000:1000"
  read_only: true
  tmpfs: [/tmp, /run]                                      # writable scratch for the child PIDs
  cap_drop: [ALL]
  security_opt: [no-new-privileges:true]
  mem_limit: ${HLH_INFER_MEM:-4g}                          # tier-scaled by image_config, not flat
  healthcheck:
    # The combined image is FROM the boofinity base, which ships python, so the
    # probe uses urllib (no wget/curl dependency). Probe path is llama-swap's
    # own readiness endpoint on 9620 - confirm the exact v226 path (/v1/models
    # vs a dedicated readiness route) before relying on it (task below).
    test: ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9620/v1/models').status==200 else 1)\" || exit 1"]
    interval: 30s
    timeout: 5s
    retries: 3
    start_period: 120s                                     # first child load can be slow
  depends_on:
    - hlh_api
  networks:
    - hlh_inference

hlh_swap_cpu:
  <<: *hlh-swap-base
  image: ${HLH_SWAP_IMAGE:-ghcr.io/indifferentketchup/hlh-swap:0.1.0-cpu}
  profiles: [bundled]

hlh_swap_gpu:
  <<: *hlh-swap-base
  image: ${HLH_SWAP_IMAGE:-ghcr.io/indifferentketchup/hlh-swap:0.1.0-cuda}
  profiles: [bundled-gpu]
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]
```

`hlh_swap` **keeps** `read_only: true`: with the child-process topology there is
no Docker socket, so the container needs only the documented writable exceptions
- `LD_LIBRARY_PATH=/app` for the llama.cpp child libs and `HOME=/cache` for the
boofinity child's caches, plus tmpfs `/tmp` and `/run` for child scratch. It
binds `0.0.0.0` per the CLAUDE.md "bundled services bind 0.0.0.0" rule and is
reachable only on the internal `hlh_inference` network. Port `9620` is the new
internal front-door port (9300/9304 are held by sibling projects; 96xx is the
project's range). The GPU variant owns the single `deploy.resources` GPU
reservation, and because only one child runs at a time, the one combined
container is the sole GPU consumer.

The `cpu` and `cuda` builds differ only in the combined image tag and the
boofinity child's `--device` / VL model ids; both share the same llama-swap
config file. Per-device differences are supplied to the boofinity child through
the `boof_cmd` macro in the image's bundled config copy, which the CUDA build
ships with `--device cuda` and the two VL model ids and the CPU build ships with
`--device cpu` and no VL ids. (Equivalently, a single config with the
`--device`/VL flags read from env keeps one file; the shipped approach is a
per-variant config baked into each image, kept byte-identical to
`hlh_swap/config.yaml` except for those device/VL tokens. The static-config-for-
v1 rule still holds: there is no per-tier renderer.)

### COMPOSE_PROFILES gating

- `bundled` (CPU tiers) -> `hlh_swap_cpu`.
- `bundled-gpu` (GPU tiers) -> `hlh_swap_gpu`.
- `external` tier -> no profile, neither starts (bring-your-own endpoint).

`docker compose --profile bundled config` and `--profile bundled-gpu config`
must each resolve exactly one `hlh_swap` service, with the standalone
`hlh_chat` and `hlh_infer` services no longer present.

### The `--url-prefix /v1` flag on the boofinity child

The boofinity child's `cmd:` passes `--url-prefix /v1`. boofinity's `url_prefix`
defaults to empty (`/opt/boofinity/libs/boofinity/boofinity/env.py:207-208`,
`default=""`); without the prefix the boofinity routes would be `/embeddings`,
`/rerank`, `/mm_embeddings`, `/mm_rerank` (no `/v1`), and the OpenAI-compat
`/v1/...` paths the HLH clients post to would 404. The flag moves every boofinity
route under `/v1`, so llama-swap proxies `model=qwen3-embed` to the boofinity
child's `/v1/embeddings`. We set the prefix via the boofinity CLI flag
`--url-prefix /v1` (cli.py:252), NOT via an env var: no `INFINITY_*` env var
appears in HLH config. (The boofinity fork still namespaces its env vars
`INFINITY_` internally at `env.py:53`, but that is fork-internal and out of
scope; the CLI flag is the supported HLH-side knob.)

### The `--dtype ${HLH_INFER_DTYPE:-float32}` flag on the boofinity child

`--dtype ${HLH_INFER_DTYPE:-float32}` on the boofinity child follows
`/opt/boofinity/DEPLOY.md`: the Pascal P104 (sm_61) test host is pathologically
slow at fp16, and fp32 matches the validated CPU parity. The default is
`float32` for Pascal safety. Operators on Ampere or newer set
`HLH_INFER_DTYPE=bfloat16` in `.env` to halve VRAM and speed up at no accuracy
loss on those cards. The float32 default is a known limitation: it doubles VRAM
versus bf16 on GPUs that support bf16, so the gpu-4gb/gpu-8gb headroom math
assumes the operator overrides on capable hardware. A
compute-capability-aware automatic default is deferred to a follow-up
(boofinity's `gpu-multistack-acceleration` change).

`HLH_INFER_DTYPE` is one of the `image_config.write_tier_env` managed keys (see
below) so a tier write seeds the default `float32` value; the operator may then
override it.

---

## models.ini changes (remove embed/rerank)

`[qwen3-embed]` and `[qwen3-reranker]` move to the boofinity child, so both
sections are deleted from `hlh_chat/models.ini` and
`hlh_orchestra/templates/models.ini`. `[medgemma]`, `[gemma-tasks]`,
`[qwen-chat]`, and the `[*]` global block are kept unchanged and are served by
the llama-server child, which reads `models.ini` from `hlh_models:/models:ro`.
After the edit both files must remain in sync for the surviving sections (the
existing `[*]` divergence - primary has the full tuning block, template has only
`sleep-idle-seconds` - is expected and unchanged).

This is one-way safe within this folder: nothing in folder B reads the removed
sections. Folder C flips the embedding/reranker providers to the boofinity model
ids; until then the providers still resolve `qwen3-embed`/`qwen3-reranker`
against `hlh_chat:9610`, which the llama-server child no longer serves - so this
folder's compose + provider rebind must land together at deploy time (noted in
tasks as a deploy-ordering constraint, the rebind itself being folder C).

---

## image_config.py changes

`_MANAGED_KEYS` grows to write the combined front-door image, the tier-scaled
infer memory, and the boofinity dtype:

```python
LLAMA_CPP_VERSION = "b9660"
LLAMA_SWAP_VERSION = "v226"
BOOFINITY_VERSION = "0.1.0"

_MANAGED_KEYS = (
    "HLH_SWAP_IMAGE",
    "COMPOSE_PROFILES", "HLH_MODELS_MAX", "HLH_INFER_MEM",
    "HLH_INFER_DTYPE",
)
```

`HLH_SWAP_IMAGE` replaces the old `HLH_CHAT_IMAGE` + `HLH_INFER_IMAGE` pair:
there is now a single combined image, so a single managed key. (Folder A owns
the constant rename; this folder consumes the combined-image constant.)

`HLH_INFER_DTYPE` is written with the default value `"float32"` on every tier
(Pascal-safe). The compose `--dtype ${HLH_INFER_DTYPE:-float32}` default makes
the env var optional: if unset, the boofinity child still runs float32. Managed
keys are rewritten on each tier write, so an Ampere+ operator's `bfloat16`
override belongs in a non-managed comment or is re-applied after a tier change.

`TierImages` gains `swap_image` (the combined-image tag per tier, `...-cpu` on
CPU tiers and `...-cuda` on GPU tiers) and `infer_mem` (a tier-scaled string,
e.g. `2g` on `cpu-min`, `4g` on `cpu-std`/`gpu-4gb`, `6g` on
`gpu-8gb`/`gpu-16gb`, `8g` on `gpu-24gb+`). `write_tier_env` writes
`HLH_SWAP_IMAGE` and `HLH_INFER_MEM` alongside the existing keys. The old
`infer_image`/`chat_image` fields collapse into `swap_image`.

---

## resource_policy.py (new, pure policy)

A small, dependency-free module beside `image_config.py`. No I/O, no DB, no
background task - it encodes the ADR-0002 tier semantics as data + functions:

```python
@dataclass(frozen=True)
class TierPolicy:
    coresident_roles: frozenset[str]   # roles allowed VRAM-resident together
    gemma_under_pressure: str          # "offload_cpu" | "unavailable"
    swap_group_exclusive: bool         # one exclusive group vs split groups

TIER_POLICY: dict[str, TierPolicy] = { ... }

def policy_for(tier: str) -> TierPolicy: ...
def gemma_degradation(tier: str) -> str: ...      # "offload_cpu" | "unavailable"
def coresident(tier: str) -> frozenset[str]: ...
```

- `cpu-min`, `cpu-std`, `apple-mlx`: no GPU contention; everything is CPU-bound,
  one exclusive swap group, Gemma `offload_cpu` (it is already on CPU).
- `gpu-4gb`, `gpu-8gb`: tight VRAM - one exclusive swap group; under pressure
  Gemma -> `unavailable` (warn) on `gpu-4gb`, `offload_cpu` on `gpu-8gb`.
- `gpu-16gb`: one exclusive swap group; Gemma `offload_cpu`.
- `gpu-24gb+`: roomy - the llama.cpp child and the boofinity child may coexist
  (non-exclusive groups), Gemma stays resident.

The policy informs which children may be co-resident per tier; it does not
render the swap config (v1 ships a static config - see `## Deferred (YAGNI)`).

`pipeline_status.py` gains a `swapping` stage key and a helper
`infer_backend_state()` that maps an `hlh_swap` `/v1/models` status response to
one of `loaded` / `swapping` / `unavailable`, so the frontend can render an
"embedding / model-swapping" phase. The estimate key table already has an
`unloading` entry; `swapping` is added alongside. This is the only behavioral
addition; everything else in `resource_policy.py` is pure data.

**In-scope consumers (no dead fields).** Every field on `TierPolicy` has a real
reader in this folder so nothing is dead:

- `gemma_under_pressure` is read by `pipeline_status.infer_backend_state()` (to
  decide whether a missing Gemma is reported as `unavailable` vs an offload-CPU
  slow path) and surfaced in the swapping phase payload.
- `swap_group_exclusive` is read by `doctor.py` to assert the shipped static
  config matches the tier's expectation (a roomy tier shipping the exclusive
  config is a WARN, not an ERROR, in v1 since the static config is intentional).
- `coresident_roles` is read by `pipeline_status` to label which roles (which
  child processes) may show as concurrently loaded.

If any field ends up with no consumer, scope `resource_policy.py` down to the
data module plus these two consumers rather than leaving the field unread.

---

## doctor.py changes

- New `_check_sidecar("hlh_swap", "http://hlh_swap:9620/v1/models")` in
  `run_checks` so an unreachable front-door is an ERROR.
- New boofinity-child check probing the boofinity child's readiness through the
  front-door (`http://hlh_swap:9620/v1/health`, or llama-swap's `/upstream`
  passthrough to the boofinity alias) - ERROR on connection refused, WARN on
  non-200 (still loading), OK on 200. There is no separate `hlh_infer`
  container to probe; the boofinity child is reachable only via `hlh_swap`.
- `_check_image_tier_match`: compare `HLH_SWAP_IMAGE` against
  `expected.swap_image` so a stale combined-image pin is flagged.
- New `_check_embed_rebind_consistency()`: B removes `[qwen3-embed]` /
  `[qwen3-reranker]` from `models.ini`, but the bundled embed/rerank providers
  are only repointed to `hlh_swap:9620` in folder C. If B and C deploy out of
  order, the intermediate state is: the llama-server child no longer serves those
  aliases AND a bundled embed/rerank provider row still has `base_url`
  `http://hlh_chat:9610` - so embed/rerank silently 404. The check reads the
  bundled embed and rerank provider rows; if either still targets
  `hlh_chat:9610` while `models.ini` lacks the matching section, it reports
  ERROR with the remedy "deploy folder C's provider rebind". This surfaces the
  un-rebound state as a boot-time error rather than a silent retrieval failure.

---

## Guardrails

**Must Have:**
- `hlh_swap` is the only inference port reachable to `hlh_api`; it binds
  `0.0.0.0` on the internal `hlh_inference` network only.
- The llama.cpp child and the boofinity child run inside `hlh_swap` as child
  PIDs of llama-swap; there is no separate inference container.
- Both `models.ini` copies have `[qwen3-embed]` and `[qwen3-reranker]` removed
  and stay in sync for surviving sections.
- Both swap-config copies (`hlh_swap/config.yaml` and the orchestra template)
  are line-for-line identical.
- `hlh_swap` keeps `read_only: true`, `cap_drop: ALL`, `no-new-privileges`,
  `user: "1000:1000"`, with the documented `LD_LIBRARY_PATH=/app` and
  `HOME=/cache` exceptions plus tmpfs `/tmp`, `/run`.
- `resource_policy.py` is pure: no DB, no HTTP, no background task.
- `image_config.py` writes `HLH_SWAP_IMAGE` and tier-scaled `HLH_INFER_MEM`.

**Must NOT Have:**
- No Docker socket mounted into any container.
- No `docker` CLI dependency and no sibling-container start/stop lifecycle.
- No new long-running service; `hlh_orchestra` stays bootstrap-only.
- No provider rebind in `provider_client.py` / `bundled_providers.py` (folder C).
- No VL retrieval / image-embedding index (folder D).
- No host-published ports on `hlh_swap`.
- No `INFINITY_*` env var in HLH config (the `--url-prefix` and `--dtype` knobs
  are CLI flags).

---

## Open risks

1. **Combined image size.** The combined image is FROM the boofinity base
   (python + torch, already large) plus the copied `llama-server` binary, its
   `.so` set, and the `llama-swap` binary. It is larger than either standalone
   image. Mitigation: multi-stage COPY of only the needed binaries and libs (not
   whole image filesystems); measure the final size and keep the CUDA variant's
   torch wheel matched to the base so no duplicate CUDA runtime is pulled in.
2. **End-to-end GPU validation on operator hardware.** The swap-exclusive group,
   the single GPU reservation, child start/stop, and VRAM release on SIGTERM must
   be validated on a real GPU host. This cannot be done in an editing session;
   it is a required pre-merge step on operator GPU hardware.
3. **Exact v226 config keys.** The `cmd` / `ttl` / `healthCheckTimeout` /
   `groups` (`swap`, `exclusive`, `members`) / `${PORT}` / `startPort` key names
   and substitution syntax must be confirmed against the shipped v226 schema and
   wiki before merge. A task pins the exact keys against the running v226 image.
4. **Cold-start child swap latency.** A request after a TTL unload pays the cost
   of llama-swap restarting the child process and reloading the model. Mitigated
   by TTL tuning (chat 600s, embed/rerank 300s) and the `pipeline_status`
   `swapping` phase so the UI shows progress rather than a hang. Note this is a
   process restart, not a container restart, so it avoids container-start
   overhead.
5. **Two children must not both be resident on tight VRAM.** The llama.cpp child
   and the boofinity child both target the one GPU. The swap-exclusive
   `vram_constrained` group enforces single-residency in-process: requesting one
   child stops the other before routing, so they are never both VRAM-resident on
   constrained tiers. (This is no longer a cold-start race - llama-swap is the
   sole launcher of every child.)
6. **Deploy ordering with folder C.** Removing the embed/rerank models.ini
   sections makes the llama-server child 404 those aliases immediately, but the
   providers are repointed in folder C. The two folders must deploy together;
   this folder ships the compose + config + image but the live cutover waits on
   C's rebind. A doctor check (added in this folder) flags the un-rebound
   intermediate state where `models.ini` no longer serves
   `[qwen3-embed]`/`[qwen3-reranker]` yet a bundled embed/rerank provider still
   points at `hlh_chat:9610`.
7. **`--url-prefix /v1` is load-bearing.** boofinity's `url_prefix` defaults to
   empty (`env.py:207-208`, `default=""`). Without the prefix the boofinity child
   routes would be `/embeddings`, `/rerank`, `/mm_embeddings`, `/mm_rerank` (no
   `/v1`), and the `/v1/...` paths the HLH clients post to (proxied by llama-swap)
   would 404. We set the prefix via the boofinity CLI flag `--url-prefix /v1`
   (cli.py:252) on the boofinity child's `cmd`, NOT via an env var: no
   `INFINITY_*` env var appears in HLH config.

---

## Deferred (YAGNI)

- **Per-tier non-exclusive swap-group generation from `resource_policy.py`.** v1
  ships one static swap config with a single exclusive `vram_constrained` group,
  identical across tiers. Rendering split non-exclusive groups per tier (so
  `gpu-24gb+` keeps the chat child + the boofinity child both resident) is
  deferred. **Reopen trigger:** when an operator on `gpu-24gb+` reports that the
  swap latency between chat and embed is a real cost, or when benchmarks show
  coresidency is safe on that tier. Until then `resource_policy.py` supplies
  policy *data* to `pipeline_status`/`doctor`, not a config renderer.
- **Free-space check on `/cache`.** Out of scope; covered in folder C.

---

## Coordination note: `vision` compose profile (with folder A)

`TIER_IMAGE_MAP['gpu-24gb+'].compose_profiles` is currently
`"bundled-gpu,vision"`, but no service in `docker-compose.yml` carries a
`vision` profile (MedGemma vision is the chat model + mmproj, not a separate
service - CLAUDE.md). The stale `vision` token is **removed** from the
`gpu-24gb+` `compose_profiles` in folder A's `TIER_IMAGE_MAP` rewrite (folder A
owns that map); this folder coordinates the removal so the front-door profile
gating (`bundled` / `bundled-gpu` only) stays clean. `write_tier_env`'s
"preserve operator-added `vision` profile" branch (`image_config.py:123-124`) is
left intact - it only re-adds `vision` if an operator put it there, which is a
no-op once the seeded value drops it.

---

## Backward compatibility

- `external` tier: unaffected - no bundled profiles, `hlh_swap` does not start.
- `_check_image_tier_match` already tolerates empty image env (returns OK
  "using defaults"), so a pre-rename `.env` does not error the doctor; it now
  reads `HLH_SWAP_IMAGE` for the combined image.
- The llama.cpp and boofinity workloads are unchanged in behavior; they just run
  as child processes of `hlh_swap` rather than as standalone containers.
