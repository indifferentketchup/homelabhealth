# Design: boofinity-image-pipeline

**Date:** 2026-06-16

---

## A1 - boofinity GHCR publish workflow (lives in the boofinity repo)

### Where the build runs

The build job is authored in `indifferentketchup/boofinity`, NOT in
homelabhealth. Rationale:

- The Dockerfiles (`libs/boofinity/Dockerfile.cpu_auto`,
  `libs/boofinity/Dockerfile.nvidia_auto`) and their build context live in the
  boofinity repo. A workflow there builds from `${{ github.workspace }}` with no
  cross-repo checkout.
- The image version tracks `pyproject.toml` version (`0.1.0`), which is owned by
  the boofinity repo. Tagging there keeps the version source-of-truth and the
  publish trigger co-located.
- homelabhealth consumes the published tag only. It never builds boofinity. This
  matches how the stack consumes `ghcr.io/ggml-org/llama.cpp` (a third-party
  published image) rather than building it.

### What the workflow does

Two matrix legs, one per Dockerfile:

| Leg | Dockerfile | Tag |
|-----|------------|-----|
| cpu | `libs/boofinity/Dockerfile.cpu_auto` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` |
| cuda | `libs/boofinity/Dockerfile.nvidia_auto` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` |

- Trigger: push of a `v0.1.0` tag (or manual `workflow_dispatch`), so the build
  is deliberate and not run on every commit.
- **Build ref (load-bearing):** the image MUST be built from the boofinity ref
  that contains the VL / `causal_lm` commits (the `ik-main` branch, or a tag cut
  from it), NOT `origin/main`. The `/v1/mm_embeddings` and `/v1/mm_rerank` routes
  and the VL model classes the bundled GPU stack relies on (folders B/D) live on
  `ik-main`; building from `origin/main` would publish an image that 404s the
  `mm_` routes. The `v0.1.0` tag is therefore cut from `ik-main`. Pushing /
  merging `ik-main` (and cutting the tag) in the separate boofinity repo is an
  **operator prerequisite** for this folder (Open Risk below).
- Auth: `permissions: packages: write` plus `docker/login-action` against
  `ghcr.io` with `${{ github.actor }}` / `${{ secrets.GITHUB_TOKEN }}`. The
  workflow token carries `write:packages` inside Actions, so the manual
  `gh auth refresh --scopes write:packages` dance (CLAUDE.md) is only needed for
  a one-off local push, not for the CI path.
- Both Dockerfiles use multi-stage builds (`FROM ubuntu:22.04` for cpu,
  `FROM nvidia/cuda:12.9.0-base-ubuntu22.04` for cuda) and run
  `boofinity v2 --preload-only --no-model-warmup` as a build-time smoke check
  before setting `ENTRYPOINT ["boofinity"]` on default port 7997.

### GHCR visibility (the cross-repo pull problem)

New GHCR packages default to **private**. homelabhealth operators pull the image
during `bootstrap.py:pull_image`, which always pulls (CLAUDE.md: never reintroduce
skip-if-present) and runs with no GHCR credentials on a fresh self-hoster host. A
private package therefore breaks first-time setup with an auth error.

**Decision:** After the first successful publish, flip both package visibilities
to **public** at
`github.com/users/indifferentketchup/packages/container/boofinity/settings`.
This mirrors the GHCR convention already documented in CLAUDE.md for the
homelabhealth images. The build task in tasks.md includes this flip and an
unauthenticated `docker buildx imagetools inspect` as the verification gate.

### Pascal note (downstream, folder B)

Pascal-class GPUs (no bf16) need `--dtype float32` passed to boofinity at
runtime. That is a runtime flag on the `hlh_infer` service, owned by folder B.
It is recorded here only so the image-layer reader knows the image itself is not
Pascal-specialized; one image serves all CUDA tiers and the dtype is selected at
launch.

### apple-mlx architecture note (JD-010)

The `apple-mlx` and the CPU tiers all map to the `-cpu` tag. Apple Silicon hosts
are `linux/arm64` under Docker. The cpu image MUST therefore be multi-arch
(`linux/amd64` + `linux/arm64`) for a native `apple-mlx` pull; otherwise the
`apple-mlx` tier runs the `linux/amd64` cpu image under emulation (qemu), which
works but is materially slower for embed/rerank. **Decision:** if the boofinity
cpu publish is single-arch `amd64` only, document the emulation perf caveat in
the CHANGELOG rather than silently shipping a slow `apple-mlx` path. Whether the
boofinity Dockerfile build produces an `arm64` leg is unconfirmed here and is a
flagged risk (Open Risks): if the `arm64` build is unconfirmed, `apple-mlx` is
emulation-only until a multi-arch publish lands.

---

## A2 - image_config.py pin rewrite

### Constants

`backend/services/image_config.py:18-19` today:

```python
LLAMA_CPP_VERSION = "b9628"
INFINITY_VERSION = "0.0.77"
```

Becomes:

```python
LLAMA_CPP_VERSION = "b9660"
LLAMA_SWAP_VERSION = "v226"
BOOFINITY_VERSION = "0.1.0"
```

`INFINITY_VERSION` is removed (now-dead; no reader survives the rewrite). The
grep gate in tasks.md confirms zero `INFINITY_VERSION` and zero
`michaelf34/infinity` references remain in `backend/`.

### TIER_IMAGE_MAP infer_image rewrite

Every `infer_image` entry (`image_config.py:30-79`) moves from
`michaelf34/infinity:{INFINITY_VERSION}[-cpu]` to the fork tag. The cpu/cuda
suffix follows the tier's hardware class:

| Tier | Old infer_image | New infer_image |
|------|-----------------|-----------------|
| `cpu-min` | `michaelf34/infinity:0.0.77-cpu` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` |
| `cpu-std` | `michaelf34/infinity:0.0.77-cpu` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` |
| `gpu-4gb` | `michaelf34/infinity:0.0.77` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` |
| `gpu-8gb` | `michaelf34/infinity:0.0.77` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` |
| `gpu-16gb` | `michaelf34/infinity:0.0.77` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` |
| `gpu-24gb+` | `michaelf34/infinity:0.0.77` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cuda` |
| `apple-mlx` | `michaelf34/infinity:0.0.77-cpu` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` |
| `external` | `michaelf34/infinity:0.0.77-cpu` | `ghcr.io/indifferentketchup/boofinity:0.1.0-cpu` |

The upstream `-cuda` tag did not exist (the GPU tiers used the unsuffixed tag);
the fork standardizes on an explicit `-cuda` suffix, so the GPU tiers gain a
suffix. The interpolation uses `{BOOFINITY_VERSION}` so a future version bump is
one constant edit.

The `chat_image` entries (llama.cpp) keep their existing shape and pick up the
`b9660` bump automatically via the `{LLAMA_CPP_VERSION}` interpolation.

### compose_profiles: drop the stale `vision` token (V10)

`TIER_IMAGE_MAP['gpu-24gb+'].compose_profiles` is currently
`"bundled-gpu,vision"`, but no service in `docker-compose.yml` carries a `vision`
profile (MedGemma vision is the chat model + mmproj, not a separate service -
CLAUDE.md). The stale `vision` token is removed here so the seeded value is
`"bundled-gpu"`. This folder owns the `TIER_IMAGE_MAP` rewrite, so it owns this
removal; folder B coordinates and relies on it for clean front-door profile
gating. The `write_tier_env` "preserve operator-added `vision`" branch
(`image_config.py:123-124`) is left intact - it is a no-op once the seeded value
drops `vision`. Aside from this one token and the `infer_image` rewrite, no other
`TierImages` field (`models_max`) changes.

`LLAMA_SWAP_VERSION` is added as a module constant only. It is not yet read by
`TIER_IMAGE_MAP` or `write_tier_env` (the front-door image wiring is folder B).
Defining it here gives folders B/C/D one import target.

### write_tier_env

`write_tier_env` is unchanged. It already writes `HLH_INFER_IMAGE` from
`images.infer_image` (`image_config.py:128`); the value it writes is simply the
new fork tag after the map rewrite. No new managed key is added in this folder.

---

## A3 - .env.example

`.env.example` (around line 39) currently documents the managed override:

```
# HLH_INFER_IMAGE=michaelf34/infinity:0.0.77-cpu
```

Becomes:

```
# HLH_INFER_IMAGE=ghcr.io/indifferentketchup/boofinity:0.1.0-cpu
```

The `HLH_CHAT_IMAGE` comment is also bumped `server-b9628` to `server-b9660` to
match `LLAMA_CPP_VERSION`. No `LLAMA_SWAP` env var is added in this folder: the
front-door service has no compose entry yet, so a managed `HLH_SWAP_IMAGE`
override would be dead. It is added in folder B alongside the service. This keeps
`.env.example` honest about what the running stack actually reads.

---

## A4 - bootstrap.py image defaults

`hlh_orchestra/bootstrap.py:48-49` hardcodes the chat image defaults:

```python
CHAT_IMAGE_CPU = os.environ.get("HLH_CHAT_IMAGE_CPU", "ghcr.io/ggml-org/llama.cpp:server-b9628")
CHAT_IMAGE_GPU = os.environ.get("HLH_CHAT_IMAGE_GPU", "ghcr.io/ggml-org/llama.cpp:server-cuda-b9628")
```

Both `b9628` defaults bump to `b9660` to match `LLAMA_CPP_VERSION`. The
`pull_image` always-pull behavior (CLAUDE.md: do not reintroduce
skip-if-present) is preserved; only the default tag string changes. If bootstrap
references an infinity image default, it is rewritten to the fork tag in the same
pass; the grep in tasks.md confirms no `michaelf34/infinity` string survives in
`hlh_orchestra/`.

---

## Cross-folder dependency

Folders B (llama-swap front-door + `hlh_infer` service), C (resource policy), and
D (dual-space VL retrieval) all read `BOOFINITY_VERSION`, `LLAMA_SWAP_VERSION`,
and the rewritten `TIER_IMAGE_MAP` from this folder. This folder must land first
so those constants exist. Until folder B adds the `hlh_infer` service to
`docker-compose.yml`, the new `infer_image` value is defined but unused (the
"ghost service" state described in `docs/CONTEXT.md`).

---

## Guardrails

**Must Have:**
- `BOOFINITY_VERSION = "0.1.0"`, `LLAMA_CPP_VERSION = "b9660"`,
  `LLAMA_SWAP_VERSION = "v226"` present in `image_config.py`.
- Every `TIER_IMAGE_MAP` `infer_image` resolves to a
  `ghcr.io/indifferentketchup/boofinity:0.1.0-{cpu,cuda}` string.
- Zero `michaelf34/infinity` and zero `INFINITY_VERSION` references remain under
  `backend/` and `hlh_orchestra/`.
- Published tags are public and resolvable via
  `docker buildx imagetools inspect`.

**Must NOT Have:**
- No `hlh_infer` service added to `docker-compose.yml`.
- No llama-swap service wiring beyond the version constant.
- No schema changes, no new Python dependencies.
- No `HLH_SWAP_IMAGE` env var (deferred to folder B).

---

## Open risks

- **CI home (low).** The build job in the boofinity repo means the homelabhealth
  CHANGELOG and tags do not by themselves prove the image exists. Verification
  must be the digest inspect, not "the workflow ran" (mirrors the CLAUDE.md note
  that a deploy is verified by running digest, not by bootstrap running).
- **GHCR cross-repo pull auth (moderate).** Covered by the visibility flip in
  A1. If a future package re-creates private (e.g., repo transfer), first-time
  setup breaks again with an opaque auth error; the doctor check in folder B
  should surface this rather than letting `pull_image` fail bare.
- **ik-main build ref (operator prerequisite, high).** The published image MUST
  be built from the boofinity ref containing the VL / `causal_lm` commits
  (`ik-main`, or a tag cut from it), not `origin/main`. Pushing / merging
  `ik-main` and cutting the `v0.1.0` tag happens in the separate
  `indifferentketchup/boofinity` repo and cannot be done from this editing
  session. It is an operator prerequisite; until it lands, the published image
  would 404 `/mm_rerank` etc. A verification task confirms the published image
  serves the `mm_` routes before this folder is marked shippable.
- **apple-mlx arm64 multi-arch (low/moderate, unconfirmed).** Whether the
  boofinity cpu publish produces a `linux/arm64` leg is unconfirmed here. If it
  does not, `apple-mlx` runs the `amd64` cpu image under emulation (slower); the
  CHANGELOG documents the caveat. A multi-arch publish is the proper fix and is
  operator-confirmable against the boofinity build.
