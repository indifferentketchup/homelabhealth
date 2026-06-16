# Tasks: boofinity-inference-frontdoor

**Date:** 2026-06-16

Order: B3 (models.ini removal) and B2 (swap config) are independent. B2b (the
combined Dockerfile) is independent of compose. B1 (compose) depends on B2/B2b
existing for the bind-mount path and the image tag. B4/B5/B6 are Python and
independent of compose. B7 (verify edit) lands last. The live cutover (provider
rebind) is folder C and must deploy alongside this folder - see the
deploy-ordering note at the end.

---

## B2.1 - Create hlh_swap/config.yaml (child-process routing)

- [ ] Create `hlh_swap/config.yaml` with a `models:` map per design.md. Define
      `medgemma`, `qwen-chat`, `gemma-tasks` whose `cmd:` launches the
      **llama-server child** (`llama-server --models-preset /models/models.ini
      --host 127.0.0.1 --port ${PORT}`) with `ttl: 600`.
- [ ] Define `qwen3-embed`, `qwen3-reranker`, `qwen3-vl-embed`, `qwen3-vl-rerank`
      whose `cmd:` launches the **boofinity child** (`boofinity v2 --model-id ...
      --url-prefix /v1 --dtype ${HLH_INFER_DTYPE:-float32} --host 127.0.0.1
      --port ${PORT}`) with `ttl: 300`.
- [ ] Add a `macros:` block for `llama_cmd` and `boof_cmd` and reference them via
      `${llama_cmd}` / `${boof_cmd}` in each model's `cmd:`.
- [ ] Set the top-level `healthCheckTimeout: 120` and `startPort: 5800`.
- [ ] Confirm there is NO Docker socket reference, NO `docker start`/`docker
      stop`, and NO `proxy:` upstream URL in the config - the backends are child
      processes, not sibling containers.

**Acceptance:** `python3 -c "import yaml; d=yaml.safe_load(open('hlh_swap/config.yaml')); assert set(d['models'])>= {'medgemma','qwen3-embed','qwen3-vl-rerank'}"` exits 0; `grep -c 'docker\.sock\|docker start\|docker stop' hlh_swap/config.yaml` returns 0.

## B2.2 - Add the swap-exclusive group

- [ ] In `hlh_swap/config.yaml` add a `groups:` entry `vram_constrained` with
      `swap: true`, `exclusive: true`, and `members:` listing all seven aliases,
      so the llama-server child and the boofinity child are never both VRAM-
      resident.

**Acceptance:** `python3 -c "import yaml; g=yaml.safe_load(open('hlh_swap/config.yaml'))['groups']['vram_constrained']; assert g['swap'] and g['exclusive'] and len(g['members'])==7"` exits 0.

## B2.3 - Confirm the exact v226 config keys

- [ ] Confirm the `cmd` / `ttl` / `healthCheckTimeout` / `groups` (`swap`,
      `exclusive`, `members`) / `startPort` / `${PORT}` key names and macro
      substitution syntax against the shipped `llama-swap:v226` schema and wiki.
      Adjust `hlh_swap/config.yaml` to the confirmed keys if any differ.

**Acceptance:** the keys used in `hlh_swap/config.yaml` match the v226 schema (documented in the task notes).

## B2.4 - Mirror swap config into the orchestra template

- [ ] Copy `hlh_swap/config.yaml` to `hlh_orchestra/templates/swap_config.yaml`
      byte-for-byte.
- [ ] In `hlh_orchestra/bootstrap.py` (near `MODELS_INI_TEMPLATE` at line 57 and
      `MODELS_INI_PATH` at line 61) add `SWAP_CONFIG_TEMPLATE` /
      `SWAP_CONFIG_PATH` constants and extend `write_templates` (line 189) to
      copy the swap config into the `hlh_config` volume.

**Acceptance:** `diff hlh_swap/config.yaml hlh_orchestra/templates/swap_config.yaml` reports no differences.

---

## B2b.1 - Create the combined hlh_swap/Dockerfile (cpu + cuda)

- [ ] Create `hlh_swap/Dockerfile` as a multi-stage build per design.md: FROM the
      boofinity base (`ARG BOOFINITY_BASE`, default `...:0.1.0-cpu`), COPY the
      `llama-server` binary + its `.so` libs from `ARG LLAMA_CPP_IMAGE`
      (`ghcr.io/ggml-org/llama.cpp:server-b9660`), COPY the `llama-swap` binary
      from `ARG LLAMA_SWAP_IMAGE` (`ghcr.io/mostlygeek/llama-swap:v226`), set
      `LD_LIBRARY_PATH=/app`, `HOME=/cache`, `HF_HOME=/cache`, `HF_HUB_OFFLINE=1`,
      and `ENTRYPOINT ["/usr/local/bin/llama-swap"]`.
- [ ] Document the CUDA variant: same Dockerfile with
      `BOOFINITY_BASE=...:0.1.0-cuda` and
      `LLAMA_CPP_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda-b9660`.
- [ ] Verify the COPY source paths against the published b9660 and v226 image
      layouts (`/app/llama-server`, the `.so` set, the `llama-swap` binary
      location); adjust the COPY lines to the real paths.

**Acceptance:** `docker build -f hlh_swap/Dockerfile --build-arg BOOFINITY_BASE=ghcr.io/indifferentketchup/boofinity:0.1.0-cpu -t hlh-swap:test .` produces an image whose entrypoint is `llama-swap` and which contains `llama-server`, `llama-swap`, and `boofinity` on PATH.

## B2b.2 - Build and tag both combined-image variants

- [ ] Build `ghcr.io/indifferentketchup/hlh-swap:<ver>-cpu` and `...-cuda` from
      `hlh_swap/Dockerfile` with the matching base args, and record the final
      image sizes (Open Risk: combined image size).

**Acceptance:** both tags build; `docker run --rm --entrypoint sh hlh-swap:<ver>-cpu -c 'command -v llama-server && command -v llama-swap && command -v boofinity'` prints three paths.

---

## B3.1 - Remove [qwen3-embed] / [qwen3-reranker] from hlh_chat/models.ini

- [ ] In `hlh_chat/models.ini`, delete the `[qwen3-embed]` section (lines 49-57)
      and the `[qwen3-reranker]` section (lines 59-66), including their leading
      comment blocks.
- [ ] Confirm `[medgemma]`, `[gemma-tasks]`, `[qwen-chat]`, and `[*]` remain;
      these are served by the llama-server child reading `models.ini` from
      `hlh_models:/models:ro`.

**Acceptance:** `grep -c 'qwen3-embed\|qwen3-reranker' hlh_chat/models.ini` returns 0; `grep -c '\[medgemma\]\|\[gemma-tasks\]\|\[qwen-chat\]' hlh_chat/models.ini` returns 3.

## B3.2 - Mirror the removal in the orchestra template

- [ ] In `hlh_orchestra/templates/models.ini`, delete the same two sections if
      present.
- [ ] `diff hlh_chat/models.ini hlh_orchestra/templates/models.ini` shows only
      the expected `[*]` divergence (primary has the full tuning block; template
      has only `sleep-idle-seconds`); the surviving model sections are identical.

**Acceptance:** `grep -c 'qwen3-embed\|qwen3-reranker' hlh_orchestra/templates/models.ini` returns 0.

---

## B1.1 - Replace standalone services with the hlh_swap pair in docker-compose.yml

- [ ] Remove the standalone `hlh_chat_cpu`/`hlh_chat_gpu` and any `hlh_infer`
      service definitions; their work now runs as child processes of `hlh_swap`.
- [ ] Add an `x-hlh-swap-base` anchor (top-level, like the former
      `x-hlh-chat-base`) with `read_only: true`, `cap_drop: [ALL]`,
      `no-new-privileges`, `user: "1000:1000"`, tmpfs `/tmp` + `/run`, volumes
      `hlh_models:/models:ro`, `hlh_infer_cache:/cache`, and
      `./hlh_swap/config.yaml:/config/config.yaml:ro`, env `HF_HOME=/cache`,
      `HOME=/cache`, `HF_HUB_OFFLINE=1`, `LD_LIBRARY_PATH=/app`,
      `mem_limit: ${HLH_INFER_MEM:-4g}`, command
      `--config /config/config.yaml --listen 0.0.0.0:9620`, healthcheck on
      llama-swap's readiness endpoint with `start_period: 120s`, network
      `hlh_inference`. Do NOT set any `INFINITY_*` env var. Do NOT mount the
      Docker socket.
- [ ] Add `hlh_swap_cpu` (`<<: *hlh-swap-base`, image
      `${HLH_SWAP_IMAGE:-ghcr.io/indifferentketchup/hlh-swap:0.1.0-cpu}`,
      `profiles: [bundled]`).
- [ ] Add `hlh_swap_gpu` (`<<: *hlh-swap-base`, image `...:0.1.0-cuda`,
      `profiles: [bundled-gpu]`, `deploy.resources.reservations.devices` nvidia
      count 1).

**Acceptance:** `docker compose --profile bundled config | python3 -c "import sys,yaml; d=yaml.safe_load(sys.stdin); s=d['services']; assert 'hlh_swap_cpu' in s and 'hlh_chat_cpu' not in s; assert s['hlh_swap_cpu']['networks']==['hlh_inference']"` exits 0; `docker compose --profile bundled config | grep -c 'docker\.sock'` returns 0.

## B1.1a - Confirm read_only with the documented exceptions

- [ ] Keep `read_only: true` on `hlh_swap`. The child-process topology needs no
      Docker socket, so the only writable exceptions are `LD_LIBRARY_PATH=/app`
      (llama.cpp child libs), `HOME=/cache` (boofinity child caches), and the
      tmpfs mounts `/tmp` + `/run` for child scratch.

**Acceptance:** `docker compose --profile bundled config | python3 -c "import sys,yaml; s=yaml.safe_load(sys.stdin)['services']['hlh_swap_cpu']; assert s.get('read_only') is True and 'ALL' in s['cap_drop']"` exits 0.

## B1.2 - Configure the boofinity child flags (--url-prefix /v1, --dtype)

- [ ] In the boofinity child's `cmd:` (the `boof_cmd` macro in
      `hlh_swap/config.yaml`, baked per-variant into the combined image), pass
      `--url-prefix /v1` (boofinity `cli.py:252`); it is load-bearing because
      boofinity's `url_prefix` defaults to empty (`env.py:207-208`), so the
      `/v1/...` routes the HLH clients post to would otherwise 404. Use the CLI
      flag, NOT an env var.
- [ ] Pass `--dtype ${HLH_INFER_DTYPE:-float32}` (Pascal-safe default) on the
      boofinity child; the CUDA variant adds `--device cuda` and the two VL model
      ids `--model-id Qwen/Qwen3-VL-Embedding-2B` + `--model-id
      Qwen/Qwen3-VL-Reranker-2B`; the CPU variant uses `--device cpu` and no VL
      ids.

**Acceptance:** `grep -c -- '--url-prefix' hlh_swap/config.yaml` >= 1; `grep -c 'INFINITY' hlh_swap/config.yaml` returns 0; the CUDA-variant config contains `Qwen3-VL-Reranker-2B`.

## B1.2a - Verify llama-swap readiness route + probe binary

- [ ] Confirm the combined image ships `python` for the healthcheck probe (it is
      FROM the boofinity base, which has python); the probe uses `urllib`, no
      wget/curl dependency.
- [ ] Confirm llama-swap's v226 readiness route on port 9620 (`/v1/models` vs a
      dedicated readiness endpoint); align the `hlh_swap` healthcheck `test:` to
      the confirmed path.
- [ ] Confirm the boofinity child health route under `--url-prefix /v1`
      (is it `/v1/health` or does `/health` stay unprefixed?) against boofinity's
      router; the doctor boofinity-child check uses the confirmed path through
      `hlh_swap`.
- [ ] After a live `bundled` bring-up, POST to the front-door `/v1/embeddings`,
      `/v1/rerank`, `/v1/mm_embeddings`, `/v1/mm_rerank` (GPU for the mm_ routes)
      via `docker exec hlh_api python -c "import asyncio,httpx; ..."` and confirm
      none 404.

## B1.3 - Declare the hlh_infer_cache volume

- [ ] In the `volumes:` block (`docker-compose.yml:242-248`) add
      `hlh_infer_cache:`. (`hlh_models` already exists.)

**Acceptance:** `docker compose config | python3 -c "import sys,yaml; assert 'hlh_infer_cache' in yaml.safe_load(sys.stdin)['volumes']"` exits 0.

## B1.4 - Validate compose for both profiles

- [ ] `docker compose --profile bundled config -q` exits 0 (no schema errors).
- [ ] `docker compose --profile bundled-gpu config -q` exits 0.
- [ ] Confirm no host ports and no Docker socket on `hlh_swap`:
      `docker compose --profile bundled-gpu config | python3 -c "import sys,yaml; s=yaml.safe_load(sys.stdin)['services']['hlh_swap_gpu']; assert s.get('ports') is None; assert all('docker.sock' not in str(v) for v in s.get('volumes',[]))"` exits 0.

**Acceptance:** both `config -q` invocations exit 0.

---

## B4.1 - Add swap/version pins and managed keys to image_config.py

- [ ] In `backend/services/image_config.py:18`, alongside `LLAMA_CPP_VERSION`,
      add `LLAMA_SWAP_VERSION = "v226"` and `BOOFINITY_VERSION = "0.1.0"`.
- [ ] Extend `_MANAGED_KEYS` (line 84) to include `"HLH_SWAP_IMAGE"`,
      `"HLH_INFER_MEM"`, and `"HLH_INFER_DTYPE"`. The old `HLH_CHAT_IMAGE` /
      `HLH_INFER_IMAGE` pair collapses into the single combined `HLH_SWAP_IMAGE`.

**Acceptance:** `python3 -c "from backend.services import image_config as c; assert {'HLH_SWAP_IMAGE','HLH_INFER_MEM','HLH_INFER_DTYPE'} <= set(c._MANAGED_KEYS)"` (run from repo root with the right sys.path) exits 0.

## B4.1a - Seed HLH_INFER_DTYPE default in write_tier_env

- [ ] In `write_tier_env`, write `HLH_INFER_DTYPE` with the default value
      `"float32"` (Pascal-safe) on every tier. The compose
      `--dtype ${HLH_INFER_DTYPE:-float32}` makes the env optional, but seeding it
      documents the default in `.env`; operators on Ampere+ override to
      `bfloat16`.

**Acceptance:** a unit smoke writing to a temp `.env` shows `HLH_INFER_DTYPE=float32`.

## B4.2 - Add swap_image and tier-scaled infer_mem to TierImages

- [ ] Add `swap_image: str` and `infer_mem: str` fields to the `TierImages`
      dataclass (`image_config.py:22-27`); collapse the old `chat_image` /
      `infer_image` fields into `swap_image`.
- [ ] Populate `TIER_IMAGE_MAP` (lines 30-79): `swap_image` =
      `ghcr.io/indifferentketchup/hlh-swap:{HLH_SWAP_VERSION}-cpu` on CPU tiers
      and `...-cuda` on GPU tiers; `infer_mem` scaled per tier (`2g` cpu-min,
      `4g` cpu-std/gpu-4gb/apple-mlx/external, `6g` gpu-8gb/gpu-16gb,
      `8g` gpu-24gb+).

**Acceptance:** `python3 -c "from backend.services.image_config import TIER_IMAGE_MAP as m; assert m['cpu-min'].infer_mem != m['gpu-24gb+'].infer_mem"` exits 0.

## B4.3 - Write the new keys in write_tier_env

- [ ] In `write_tier_env` (`image_config.py:126-131`), add `HLH_SWAP_IMAGE`,
      `HLH_INFER_MEM`, and `HLH_INFER_DTYPE` (default `"float32"`) to the
      `managed` dict from the tier's `TierImages`.
- [ ] Update the closing `logger.info` (lines 161-164) to include the new values.

**Acceptance:** `python3 -m py_compile backend/services/image_config.py` exits 0; a unit smoke writing to a temp `.env` shows the new lines present.

---

## B5.1 - Create backend/services/resource_policy.py

- [ ] Create `resource_policy.py` with a frozen `TierPolicy` dataclass
      (`coresident_roles`, `gemma_under_pressure`, `swap_group_exclusive`) and a
      `TIER_POLICY` dict covering every tier in `image_config.TIER_IMAGE_MAP`.
- [ ] Expose `policy_for(tier)`, `coresident(tier)`, `gemma_degradation(tier)`.
      Per ADR-0002: `gpu-4gb` -> `unavailable`; `cpu-*`/`apple-mlx` ->
      `offload_cpu`; `gpu-24gb+` -> resident (non-exclusive group).
- [ ] No DB / HTTP / asyncio imports - pure data + functions.
- [ ] Ensure every `TierPolicy` field has a real in-scope consumer (no dead
      fields): `gemma_under_pressure` read by `pipeline_status.infer_backend_state`,
      `swap_group_exclusive` read by `doctor.py`, `coresident_roles` read by
      `pipeline_status`. If a field has no consumer, drop it (scope down to the
      data module + the two consumers) rather than leaving it unread.

**Acceptance:** `python3 -c "from backend.services.resource_policy import gemma_degradation as g; assert g('gpu-4gb')=='unavailable' and g('cpu-std')=='offload_cpu'"` exits 0; `grep -E 'asyncpg|httpx|asyncio' backend/services/resource_policy.py` returns nothing; `grep -rn 'resource_policy' backend/services/pipeline_status.py backend/hlh/doctor.py` shows at least one import (real consumer).

## B5.0 - Document the static-config-for-v1 / deferred renderer decision

- [ ] Confirm `hlh_swap/config.yaml` is the single static exclusive group for v1
      (B2.2 already authors it). Do NOT add a per-tier config renderer driven by
      `resource_policy.py` - that is explicitly deferred (design.md
      `## Deferred (YAGNI)` with a reopen trigger). `resource_policy.py` informs
      which children may be co-resident per tier; it does not render the config.

**Acceptance:** `grep -c 'vram_constrained' hlh_swap/config.yaml` returns 1 (single group); no config-rendering function references `resource_policy` in the codebase.

## B5.2 - Add a swapping stage to pipeline_status.py

- [ ] In `pipeline_status._estimate_key` (`backend/services/pipeline_status.py:24-33`)
      add a `"swapping": "estimate_ms_swap"` entry to the dict.
- [ ] Add a helper (e.g. `infer_backend_state(model)`) that GETs the front-door
      `http://hlh_swap:9620/v1/models`, maps the model's status to
      `loaded` / `swapping` / `unavailable`, and returns `unavailable` on
      transport error (mirror `model_is_loaded` at lines 97-112).

**Acceptance:** `python3 -c "from backend.services.pipeline_status import _estimate_key; assert _estimate_key('swapping')=='estimate_ms_swap'"` exits 0; `python3 -m py_compile backend/services/pipeline_status.py` exits 0.

---

## B6.1 - Add hlh_swap and boofinity-child health checks to doctor.py

- [ ] In `backend/hlh/doctor.py:run_checks` (lines 470-491) add
      `await _check_sidecar("hlh_swap", "http://hlh_swap:9620/v1/models")`.
- [ ] Add a boofinity-child check probing the boofinity child's readiness through
      the front-door (`http://hlh_swap:9620/v1/health` or llama-swap's
      `/upstream` passthrough to the boofinity alias). There is no separate
      `hlh_infer` container; the boofinity child is reachable only via `hlh_swap`.

**Acceptance:** `python3 -c "src=open('backend/hlh/doctor.py').read(); assert 'hlh_swap' in src and '9620' in src"` exits 0; `grep -c 'hlh_infer:7997' backend/hlh/doctor.py` returns 0 (no standalone infer container probe).

## B6.2 - Extend _check_image_tier_match for the combined swap image

- [ ] In `_check_image_tier_match` (`doctor.py:389-415`) read
      `HLH_SWAP_IMAGE` (line 402-403 region) and append a `swap:` mismatch to
      `mismatches` when it diverges from `expected.swap_image`.

**Acceptance:** `python3 -m py_compile backend/hlh/doctor.py` exits 0; `grep -c HLH_SWAP_IMAGE backend/hlh/doctor.py` >= 1.

## B6.3 - Add the embed/rerank rebind-consistency check

- [ ] Add `_check_embed_rebind_consistency()` to `doctor.py` and register it in
      `run_checks`. It reads the bundled embed and rerank provider rows; if
      either still has `base_url = http://hlh_chat:9610` while `models.ini` no
      longer serves `[qwen3-embed]`/`[qwen3-reranker]`, report ERROR with the
      remedy "deploy folder C's provider rebind". OK when both are on
      `hlh_swap:9620`.
- [ ] `python3 -m py_compile backend/hlh/doctor.py` exits 0.

**Acceptance:** `grep -c 'hlh_chat:9610' backend/hlh/doctor.py` >= 1 (the un-rebound base_url the check compares against).

## B6.4 - Coordinate removing the stale `vision` compose profile (with folder A)

- [ ] Confirm folder A's `TIER_IMAGE_MAP` rewrite drops `vision` from
      `gpu-24gb+` `compose_profiles` (`image_config.py:64`,
      `"bundled-gpu,vision"` -> `"bundled-gpu"`). No `vision`-profile service
      exists. Leave the `write_tier_env` "preserve operator-added `vision`"
      branch (`image_config.py:123-124`) intact.

**Acceptance:** `python3 -c "from backend.services.image_config import TIER_IMAGE_MAP as m; assert 'vision' not in m['gpu-24gb+'].compose_profiles"` exits 0.

---

## B7.1 - Update verify_a1_5_hardening.sh for the combined hlh_swap service

- [ ] In `backend/scripts/verify_a1_5_hardening.sh`, replace the standalone
      `hlh_chat` / `hlh_infer` references with the single `hlh_swap` service:
      add `hlh_swap` to the container-hardening loop (it IS `read_only: true`
      now) and to the network-membership map as `[hlh_swap]='[hlh_inference]'`.
- [ ] Replace the exact `4294967296` `mem_limit` assertion with a positive-value
      check for `hlh_swap` (`[[ "$swap_mem" -ge 1073741824 ]]`), matching the
      tier-scaled `HLH_INFER_MEM`.
- [ ] Keep the no-host-ports assertion for `hlh_swap`. Add a check that no
      service mounts `/var/run/docker.sock`.

**Acceptance:** `bash -n backend/scripts/verify_a1_5_hardening.sh` exits 0; `grep -c 4294967296 backend/scripts/verify_a1_5_hardening.sh` returns 0; `grep -c 'docker.sock' backend/scripts/verify_a1_5_hardening.sh` >= 1 (the negative assertion).

---

## Cross-cutting verification

- [ ] `python3 -m py_compile $(find backend -name '*.py')` produces no errors.
- [ ] `docker compose --profile bundled config -q` and
      `docker compose --profile bundled-gpu config -q` both exit 0.
- [ ] `diff hlh_swap/config.yaml hlh_orchestra/templates/swap_config.yaml` clean.
- [ ] `grep -c 'qwen3-embed\|qwen3-reranker' hlh_chat/models.ini hlh_orchestra/templates/models.ini` returns 0 for both.
- [ ] No Docker socket anywhere: `grep -rc 'docker.sock' docker-compose.yml hlh_swap/config.yaml` returns 0 for both.
- [ ] Update `CHANGELOG.md` under `[Unreleased]` (AI / Tooling tracks) with the
      combined front-door, child-process backends, resource policy, and
      doctor-check entries.
- [ ] In the same CHANGELOG entry note the `HLH_INFER_DTYPE` default of
      `float32` and its limitation: float32 doubles VRAM versus bf16 on GPUs that
      support bf16, so Ampere+ operators should set `HLH_INFER_DTYPE=bfloat16`.

---

## Live deploy verification (deferred to a real stack)

These cannot run in an editing session; run after `docker compose up --build -d`.

- [ ] Bring up the stack on a `bundled` host:
      `docker compose --profile bundled up -d hlh_swap_cpu`.
- [ ] From inside the API container (no curl - CLAUDE.md), confirm the front-door
      routes embed to the boofinity child:
      `docker exec hlh_api python -c "import asyncio,httpx; print(asyncio.run(httpx.AsyncClient().post('http://hlh_swap:9620/v1/embeddings', json={'model':'qwen3-embed','input':['hi']})).status_code)"`
      returns 200 and a 1024-length vector.
- [ ] Confirm chat routes to the llama-server child:
      `docker exec hlh_api python -c "import asyncio,httpx; print(asyncio.run(httpx.AsyncClient(timeout=120).get('http://hlh_swap:9620/v1/models')).json())"`
      lists `medgemma` and `qwen3-embed`.
- [ ] Confirm the exclusive group swaps: request `medgemma`, then `qwen3-embed`,
      and verify only one child process holds VRAM at a time
      (`nvidia-smi` shows a single resident process), with no Docker socket and
      no second inference container in `docker ps`.
- [ ] `docker exec hlh_api python -m hlh.doctor` shows `hlh_swap_reachable` OK and
      the boofinity-child `/health` check OK (or WARN while booting, not ERROR).
- [ ] `backend/scripts/verify_a1_5_hardening.sh` passes with the tier-scaled
      `hlh_swap` memory assertion and the no-docker-socket assertion.

---

## Deploy-ordering constraint (with folder C)

Removing `[qwen3-embed]` / `[qwen3-reranker]` from `models.ini` makes the
llama-server child 404 those aliases the moment it restarts. The bundled
embedding and reranker providers still resolve them against `hlh_chat:9610` until
folder C repoints `provider_client.py` / `bundled_providers.py` at
`hlh_swap:9620`. Therefore this folder's compose + config + image changes MUST
deploy together with folder C's provider rebind. Do not ship B's `models.ini`
removal to a live stack ahead of C. (The rebind itself is out of scope here.)
