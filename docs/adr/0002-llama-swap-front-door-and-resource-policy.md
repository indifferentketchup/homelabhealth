# 0002 - llama-swap front-door with HLH-side resource policy

- **Status:** Accepted
- **Date:** 2026-06-16
- **Deciders:** indifferentketchup

## Context

Splitting embed/rerank/VL onto boofinity means two inference processes -
llama.cpp (chat/tasks/vision-mmproj) and boofinity (embed/rerank/VL) - competing
for the same GPU. On constrained tiers they cannot both be VRAM-resident. The
operator wants: when embedding runs, resources go to the embedder; on low-VRAM
hosts Gemma offloads to CPU (slow) or goes unavailable with a warning.

llama-swap (v226) was validated working with boofinity + llama.cpp as **child
processes** (see `/opt/boofinity/DEPLOY.md:93`, "llama-swap child pattern"). It
lazily starts/stops backend child processes with group/TTL semantics. The
project removed llama-swap in April (commit `86c3af5`) in favour of llama-server
router mode; this re-adopts it deliberately, now that there are two backends to
arbitrate rather than one.

## Decision

A single combined container `hlh_swap` whose entrypoint is llama-swap (v226+)
becomes the single inference front-door (port 9620, internal `hlh_inference`
network). llama-swap is both the only inference endpoint and the process
manager: its config `cmd:` lines launch the two backends as **child processes
inside the same container** -

- `llama-server --models-preset /models/models.ini ...` serving chat / tasks /
  mmproj (`medgemma`, `qwen-chat`, `gemma-tasks`), and
- `boofinity v2 --model-id ... --url-prefix /v1 --port ...` serving embed /
  rerank / VL (`qwen3-embed`, `qwen3-reranker`, and on roomy GPU tiers
  `qwen3-vl-embed`, `qwen3-vl-rerank`).

A swap-exclusive group makes the llama.cpp child and the boofinity child mutually
exclusive on constrained VRAM with TTL idle-unload, so swapping a child process
frees its VRAM. The combined image is FROM the boofinity image (python + torch +
boofinity), with the `llama-server` binary copied from
`ghcr.io/ggml-org/llama.cpp:server[-cuda]-b9660` and the `llama-swap` binary
copied from `ghcr.io/mostlygeek/llama-swap:v226`; cpu and cuda variants build
FROM the matching bases. This replaces the standalone `hlh_chat` (llama.cpp) and
`hlh_infer` (boofinity) services with child processes of `hlh_swap`. Bundled
providers point at `hlh_swap:9620` instead of `hlh_chat:9610` (the rebind itself
is folder C).

The **mechanical** load/unload is llama-swap's job (config groups + TTL). The
**policy** - which children may coexist per tier, and whether Gemma
offloads-to-CPU vs. goes unavailable-with-warning under pressure - lives HLH-side
in a tier-aware `resource_policy.py` beside `image_config.py`, with live state
surfaced through `pipeline_status.py`. No new long-running service;
`hlh_orchestra` stays bootstrap-only.

## Consequences

- **+** Solves cross-backend VRAM contention without a bespoke scheduler: the
  swap-exclusive group keeps the two children single-resident in-process.
- **+** No Docker socket, no `docker` CLI dependency, no sibling-container
  start/stop lifecycle, and no cold-start double-VRAM race - the backends are
  child PIDs of one container, not separately scheduled containers.
- **+** Reuses llama-swap's proven swap engine; HLH only encodes tier semantics it already owns.
- **+** Graceful degradation (offload / warn) is explicit and tier-driven, not silent OOM.
- **−** Re-introduces a layer removed in April; models.ini logic moves into llama-swap config.
- **−** The combined image is larger than either standalone image (FROM boofinity
  plus the copied llama-server + llama-swap binaries).
- **−** Swap latency on first request after an idle/unload, paid as a child
  process restart; mitigated by warmup + TTL tuning.
- **−** If llama-swap groups prove too coarse, a standalone resource manager is a follow-up (deliberately deferred).

## Alternatives considered

- **Sibling containers + Docker-socket control** - `hlh_chat` and `hlh_infer`
  stay as separate compose services and llama-swap swaps them with
  `docker start`/`docker stop` over a mounted `/var/run/docker.sock`. **Rejected**
  on adversarial review: the llama-swap minimal image may ship no `docker` CLI
  binary; mounting the socket grants full Docker daemon control (a
  privilege-escalation surface a `:ro` bind does not scope); and a cold
  `docker compose up` can race both GPU containers into a double-VRAM hold before
  llama-swap stops either. The child-process topology removes all three.
- **New standalone orchestrator service** - rejected for now: extra hardened
  container; llama-swap already does the mechanism. Revisit only if groups are insufficient.
- **llama-swap groups/TTL only, no HLH policy** - rejected: llama-swap has no
  knowledge of HLH tier semantics, so the offload-vs-unavailable nuance and
  pull/resource tracking would be too coarse.
