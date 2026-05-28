# Smart Orchestra Bootstrap — Design

**Date:** 2026-05-28
**Status:** Design approved, ready to build.
**Spec author:** Sam (`indifferentketchup`)

## Problem

The homelabhealth stack is 7 containers, 2 networks, 7 volumes, with profiles
for CPU/GPU/vision and a layered set of hardening directives. To install
today, the user must:

1. Clone the repo
2. Copy `.env.example` to `.env`
3. Run `docker compose --profile bundled up -d` (or `bundled-gpu`)
4. Optionally `--profile vision` for MedSigLIP

Multiple steps. Requires the compose file on disk. Requires picking a profile.
Not the one-command experience a self-hosted product should offer.

## Goal

Single command bootstraps the entire stack:

```
docker run -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/indifferentketchup/homelabhealth
```

On first run: pulls every image, creates networks and volumes, generates
secrets, starts containers in dependency order, prints
`homelabhealth is running → http://localhost:9604`.

On subsequent runs: detects existing state, starts only what's stopped,
skips pulls if images exist.

The container stays running as the lifecycle manager (the role the orchestra
already plays for vision start/stop).

## Non-goals

- **Compose CLI replacement.** Users who prefer compose can still clone the
  repo and use it. The bootstrap is an additional entry point, not a
  replacement.
- **Host-side data directories.** All persistent state stays in named Docker
  volumes. No bind mounts required.
- **Interactive wizard.** Zero-config sane defaults; overrides via `-e` env
  vars.
- **Multi-host / Kubernetes orchestration.** Single-host Docker only.

## Architecture

### Single image, two responsibilities

The `hlh_orchestra` container does both:

1. **Bootstrap** (runs once at startup): create networks, volumes, pull
   images, start containers in order
2. **Lifecycle manager** (runs continuously): existing FastAPI server on port
   9620 with `vision/start`, `vision/stop`, `vision/status` endpoints

Bootstrap runs synchronously before FastAPI starts. If bootstrap fails, the
container exits with a non-zero status and an error to stderr.

### Bootstrap module structure

New file: `hlh_orchestra/bootstrap.py`

- **Container specs** as Python dicts, equivalent to current `docker-compose.yml`.
  One spec per service: `hlh_db`, `hlh_api`, `hlh_chat`, `hlh_search`,
  `hlh_ui`, `hlh_vision_embed`. The orchestra itself is already running.
- **`detect_gpu()`** — try `docker info` to check for nvidia runtime; pick
  CPU or GPU llama.cpp image accordingly.
- **`ensure_networks()`** — create `hlh_default` and `hlh_inference`
  (idempotent).
- **`ensure_volumes()`** — create all named volumes (idempotent).
- **`pull_images()`** — pull images with progress streamed to stdout.
  Skipped on subsequent runs if images already exist.
- **`generate_secrets()`** — on first run, create `HLH_MASTER_KEY` and
  `ORCHESTRA_TOKEN`. Persist in a new `hlh_config` volume as a `.env` file
  inside `/data/config/`. Subsequent runs read existing values.
- **`start_in_order()`** — start containers respecting dependencies:
  1. `hlh_db` → wait for healthy
  2. `hlh_api` → wait for healthy
  3. `hlh_chat`, `hlh_search`, `hlh_ui` in parallel
  4. `hlh_vision_embed` is left stopped (started on demand via existing
     vision lifecycle endpoints)

### Configuration

Zero-config defaults: ports 9600 (API) and 9604 (UI), as the existing compose
file uses. Both already uncommon. Optional overrides via `-e`:

- `HLH_PORT_UI` (default: 9604)
- `HLH_PORT_API` (default: 9600)
- `HLH_PORT_SEARCH` (default: 9612)
- `HLH_CHAT_MEM` (default: 7g)
- `HLH_VERSION` (default: latest) — image tag to pull for hlh_api, hlh_ui,
  hlh_orchestra
- `HLH_REGISTRY` (default: ghcr.io/indifferentketchup)

### State and idempotency

The orchestra needs to know whether this is a first run or a restart. Cheap
detection: look for the `hlh_db` container.

- Container exists → restart path: start any stopped containers, skip pulls
  and volume creation
- Container doesn't exist → first-run path: full bootstrap

The `hlh_config` volume holds generated secrets so they survive container
recreation. The orchestra mounts it at `/data/config/`.

### Hardening preserved

Every container created by bootstrap carries the same flags as the current
compose file: `read_only`, `cap_drop: [ALL]`, `security_opt:
[no-new-privileges:true]`, per-service `mem_limit`, `user: "1000:1000"`
where applicable, internal networks where applicable.

### Output UX

Bootstrap logs to stdout. User sees pull progress, container start status,
final summary:

```
[bootstrap] checking for existing stack...
[bootstrap] first run detected
[bootstrap] detecting GPU... none (using CPU images)
[bootstrap] creating networks: hlh_default, hlh_inference
[bootstrap] creating volumes: hlh_db_data, hlh_keys, hlh_uploads, hlh_branding, hlh_history, hlh_models, hlh_config, hlh_vision_cache
[bootstrap] pulling pgvector/pgvector:pg16... done
[bootstrap] pulling ghcr.io/indifferentketchup/hlh_api:latest... done
[bootstrap] pulling ghcr.io/ggml-org/llama.cpp:server-b9282... done
[bootstrap] pulling searxng/searxng:2026.5.22-c57f772ad... done
[bootstrap] pulling ghcr.io/indifferentketchup/hlh_ui:latest... done
[bootstrap] starting hlh_db... healthy
[bootstrap] starting hlh_api... healthy
[bootstrap] starting hlh_chat, hlh_search, hlh_ui... ok
[bootstrap] done in 47s

homelabhealth is running → http://localhost:9604
[orchestra] vision lifecycle server listening on :9620
```

Foreground process. `Ctrl-C` stops the orchestra; other containers keep
running (the orchestra is just the manager — stack lifecycle is independent).

## Failure modes

- **Docker socket not mounted:** detected at startup, exit with clear message
- **Docker daemon unreachable:** ditto
- **Image pull fails:** retry with backoff (3 attempts); on final failure,
  log and exit
- **Container fails healthcheck after start:** wait up to 90s for
  `hlh_db` (slow first init), 60s for `hlh_api`; on timeout, log and exit
- **Partial state from prior failed run:** restart path detects existing
  containers and reuses them; on tag mismatch, logs a warning and recreates

## Migration / coexistence

Users on the current `docker compose` workflow are unaffected. The compose
file stays in the repo. The smart bootstrap is opt-in via the new image.

The orchestra's existing `vision/*` endpoints stay unchanged. The smart
orchestra knows about every container; the FastAPI surface still only
exposes vision lifecycle for now. Adding general lifecycle endpoints
(`/stack/restart`, etc.) is future work.

## Testing plan

1. **Cold first run on fresh host:** no containers, no volumes, no images.
   Should pull everything and come up healthy.
2. **Restart with existing state:** stop orchestra, restart — should detect
   existing state and skip pull/volume creation.
3. **Mid-bootstrap interrupt:** kill bootstrap during image pull. Restart
   should resume cleanly (retried pull picks up).
4. **GPU detection:** run on a host with NVIDIA runtime configured; verify
   GPU llama.cpp image is picked.
5. **Port override:** `-e HLH_PORT_UI=9700` should publish UI on 9700.
6. **Compose compatibility:** stack created by bootstrap should be
   indistinguishable from a `docker compose up` stack (same names, networks,
   volumes). Verify by stopping the orchestra and using `docker compose`
   against the existing containers.
