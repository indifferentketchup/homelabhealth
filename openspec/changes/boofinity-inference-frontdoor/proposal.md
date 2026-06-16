# Proposal: boofinity-inference-frontdoor

**Date:** 2026-06-16
**Status:** proposed

## Summary

Introduce a single inference front-door for the bundled stack. Today
`hlh_chat` (a llama.cpp router) serves chat, tasks, embed, rerank, and vision
from one process. This change moves embed/rerank/VL onto **boofinity** and
chat/tasks/mmproj onto **llama.cpp**, and runs both as **child processes of one
combined container** named `hlh_swap` whose entrypoint is **llama-swap (v226)**.
llama-swap is both the only inference endpoint (port 9620, internal network
`hlh_inference`) and the process manager: it launches each backend as a child
PID via its `cmd:` lines and arbitrates VRAM between them with swap groups, so
the two GPU-competing processes never both pin VRAM. It also adds a tier-aware
HLH-side resource policy that decides, under VRAM pressure, whether Gemma
offloads to CPU (slow) or goes unavailable with a warning.

This is folder **B** of the boofinity split (see `docs/adr/0001`-`0003`). It
owns the topology, the front-door config, the combined image, and the resource
policy. The model-pull mechanism and the provider rebind from `hlh_chat:9610` to
the front-door are folder **C**; native VL retrieval is folder **D**.

## Motivation

`docs/adr/0002` records the decision: splitting embed/rerank/VL onto boofinity
means two inference processes - llama.cpp (chat/tasks/vision-mmproj) and
boofinity (embed/rerank/VL) - competing for the same GPU. On constrained tiers
they cannot both be VRAM-resident. The operator wants resources to flow to the
embedder while embedding runs, and on low-VRAM hosts Gemma to either offload to
CPU or go unavailable with a clear warning rather than silently OOM.

llama-swap (v226) was validated with boofinity + llama.cpp as **child
processes** (the "llama-swap child pattern", `/opt/boofinity/DEPLOY.md:93`). It
lazily starts and stops backend child PIDs with group and TTL semantics. The
project removed llama-swap in April (`86c3af5`) in favour of llama-server router
mode; this re-adopts it deliberately now that there are two backends to
arbitrate rather than one.

The combined-container child-process topology is the deliberate replacement for
an earlier sibling-container design (llama-swap controlling `hlh_chat` and
`hlh_infer` over the Docker socket). Adversarial review found the sibling design
unsafe: the llama-swap minimal image may ship no `docker` CLI binary; mounting
the Docker socket into `hlh_swap` grants full daemon control (a
privilege-escalation surface); and a cold `docker compose up` can race both GPU
containers into a double-VRAM hold. The child-process pattern removes all three:
no socket, no `docker` CLI, no sibling lifecycle, no start/stop race. The
backends are child PIDs of one container, and the swap-exclusive group enforces
single-resident VRAM in-process.

The **mechanical** load/unload is llama-swap's job (config groups + TTL). The
**policy** - which roles may coexist per tier, and the offload-vs-unavailable
nuance under pressure - lives HLH-side in a tier-aware module beside
`image_config.py`, with live state surfaced through `pipeline_status.py`. No new
long-running service; `hlh_orchestra` stays bootstrap-only.

## Scope

| ID  | File(s) touched                                                | Type            |
|-----|----------------------------------------------------------------|-----------------|
| B1  | `docker-compose.yml`                                            | Replace `hlh_chat`/`hlh_infer` standalone services with the combined `hlh_swap` service |
| B2  | `hlh_swap/config.yaml`, `hlh_orchestra/templates/swap_config.yaml` | New front-door config with child `cmd:` lines (mirrored) |
| B2b | `hlh_swap/Dockerfile`                                           | New multi-stage combined image (cpu + cuda) |
| B3  | `hlh_chat/models.ini`, `hlh_orchestra/templates/models.ini`    | Remove `[qwen3-embed]`, `[qwen3-reranker]`; mount into `hlh_swap` |
| B4  | `backend/services/image_config.py`                             | Extend `_MANAGED_KEYS` + tier-scaled infer mem / combined swap image / dtype |
| B5  | `backend/services/resource_policy.py` (new), `backend/services/pipeline_status.py` | Tier resource policy + swap state |
| B6  | `backend/hlh/doctor.py`                                         | `hlh_swap` reachability + boofinity-child `/health` + rebind-consistency checks |
| B7  | `backend/scripts/verify_a1_5_hardening.sh`                     | `hlh_swap` mem tier-scaled; single combined inference service |

Both copies of `models.ini` and both copies of the swap config must stay in
sync per the CLAUDE.md convention ("Templates in `hlh_orchestra/templates/` must
mirror `hlh_chat/models.ini` and `searxng/settings.yml`").

## Pins

From folder A (`docs/adr/0001`, `image_config.py`):

- `LLAMA_CPP_VERSION = b9660` (`ghcr.io/ggml-org/llama.cpp:server-b9660` /
  `server-cuda-b9660`, the source of the `llama-server` binary copied into the
  combined image)
- `LLAMA_SWAP_VERSION = v226` (`ghcr.io/mostlygeek/llama-swap:v226`, the source
  of the `llama-swap` binary copied into the combined image)
- `BOOFINITY_VERSION = 0.1.0` (`ghcr.io/indifferentketchup/boofinity:0.1.0-{cpu,cuda}`,
  the base of the combined image - brings python + torch + boofinity)
- Combined image: `ghcr.io/indifferentketchup/hlh-swap:<ver>-{cpu,cuda}` (built
  by this folder's `hlh_swap/Dockerfile`).

## Locked naming

- `hlh_swap` - the combined inference container; entrypoint llama-swap, the
  single inference endpoint, the parent of the llama.cpp and boofinity child
  PIDs.
- Served aliases routed by llama-swap to the **llama-server child**: `medgemma`,
  `qwen-chat`, `gemma-tasks`.
- Served aliases routed by llama-swap to the **boofinity child**: `qwen3-embed`,
  `qwen3-reranker`, `qwen3-vl-embed`, `qwen3-vl-rerank`.
- Volume `hlh_models` mounted at `/models:ro` (llama-server GGUFs + `models.ini`).
- Volume `hlh_infer_cache` mounted at `/cache` (boofinity `HF_HOME=/cache`,
  `HOME=/cache`, `HF_HUB_OFFLINE=1`).
- Network `hlh_inference` (internal).
- boofinity child route prefix set with the CLI flag `--url-prefix /v1`; no
  `INFINITY_*` env var appears in HLH config.

## Out of scope

- Provider rebind: `provider_client.py` / `bundled_providers.py` still point at
  `hlh_chat:9610` after this change. Repointing bundled providers at
  `hlh_swap:9620` is folder C; this folder lands the front-door but does not flip
  the consumers.
- The model-pull mechanism for boofinity weights into `hlh_infer_cache`
  (folder C).
- Native dual-space VL retrieval and the new image-embedding `vector(1024)`
  index (folder D).
- The `BOOFINITY_VERSION` / `LLAMA_CPP_VERSION` pin bumps themselves landed in
  folder A; this folder consumes them.

## Risk

Moderate. The front-door is a new internal hop and a re-adoption of a layer
removed in April. The chosen topology - one combined `hlh_swap` container,
llama-server and boofinity as child PIDs of llama-swap, no Docker socket and no
sibling-container lifecycle - removes the privilege and race risks of the
rejected sibling design. The remaining open risks (documented in design.md) are:
the size of the combined image; end-to-end GPU validation on operator hardware;
confirming the exact v226 config keys and readiness-endpoint path; and the
cold-start latency when a swap restarts a child process. The GPU contention is
no longer a race: the swap-exclusive group guarantees the llama.cpp child and
the boofinity child are never both VRAM-resident.
