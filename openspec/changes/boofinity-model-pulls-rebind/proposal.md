# Proposal: boofinity-model-pulls-rebind

**Date:** 2026-06-16
**Status:** proposed

## Summary

Wire the bundled stack to actually serve text embed and text rerank from
**boofinity** behind the **llama-swap** front-door. This is folder **C** of the
boofinity split (see `docs/adr/0001`-`0003`). It does four things:

1. Adds an HF-repo snapshot pull path to `model_puller.py` alongside the
   existing single-file GGUF puller, and flips `_EMBED_SPEC` / `_RERANK_SPEC`
   from flat llama.cpp GGUFs to the safetensors repos boofinity loads
   (`Qwen/Qwen3-Embedding-0.6B`, `Qwen/Qwen3-Reranker-0.6B`), landing them in
   the HF hub cache layout inside the `hlh_infer_cache` volume.
2. Repoints the bundled chat, embed, and rerank providers from
   `http://hlh_chat:9610` to the llama-swap front-door `http://hlh_swap:9620`.
3. Adapts `rag.py`'s `_rerank_infinity` to boofinity's `/rerank` contract
   (documents as a list of strings; results carry `relevance_score` + `index`).
4. On the first boot after the embed cutover, fires a one-shot, idempotent
   `POST /api/sources/reingest-all` because switching the embedder from
   Qwen3-Embedding GGUF (Q8_0, llama.cpp last-token pooling) to the boofinity
   safetensors model produces numerically different vectors that are not
   comparable to the stored `source_chunks` embeddings.

Scope is text embed + text rerank only. Qwen3-VL embed/rerank retrieval is
folder **D**.

## Motivation

Folder B landed `hlh_swap` (front-door) and `hlh_infer` (boofinity) in compose
but deliberately did **not** flip the consumers: `bundled_providers.py` still
points embed/rerank/chat at `hlh_chat:9610`, and folder B removed the
`[qwen3-embed]` / `[qwen3-reranker]` sections from both `models.ini` copies. As
of folder B's deploy, those two aliases 404 on `hlh_chat`. This folder closes
that gap: it pulls the boofinity weights, repoints the providers at the
front-door (which routes `qwen3-embed` / `qwen3-reranker` to boofinity), and
fixes the rerank wire contract.

boofinity loads its models from the standard HuggingFace hub cache. It runs with
`HF_HOME=/cache` and `HF_HUB_OFFLINE=1` (folder B), so it never reaches the
network: the weights must already be in `/cache` in the hub's
`models--<org>--<repo>/snapshots/<rev>/` layout. The existing puller streams a
single `resolve/<rev>/<file>` URL to a flat `/models/<file>` path - wrong shape
for a multi-file safetensors repo and wrong volume. A snapshot path is needed.

The embedder change is not vector-compatible. Per the existing note in
`model_puller.py` (the bge-m3 -> Qwen3 switch on 2026-06-12), changing embed
models requires `POST /api/sources/reingest-all`. The GGUF Q8_0 -> safetensors
fp32 change is the same class of change and demands the same reingest, this time
fired automatically on cutover so retrieval is never silently wrong.

## Scope

| ID | File(s) touched | Type |
|----|-----------------|------|
| C1 | `backend/services/model_puller.py` | `ModelSpec` snapshot variant; `_EMBED_SPEC`/`_RERANK_SPEC`/`_FLAT_DEST_ROLES`; snapshot pull path; `seed_registry` |
| C2 | `backend/services/bundled_providers.py` | Chat/embed/rerank `base_url` -> `http://hlh_swap:9620` |
| C3 | `backend/services/rag.py` | `_rerank_infinity` boofinity `/rerank` contract |
| C4 | `backend/services/embeddings.py` | Confirm OpenAI-compat `/v1/embeddings` against boofinity |
| C5 | `backend/services/embed_cutover.py` (new), `backend/main.py` | One-shot idempotent reingest trigger + Settings banner flag |
| C6 | `backend/hlh/doctor.py` | `_check_model_pulls` covers snapshot rows; new `_check_infer_cache_writable` |
| C7 | `backend/routers/providers.py` | Keep verbatim 1024-dim check (no change) |
| C8 | `backend/scripts/verify_boofinity_embed_rerank.sh` (new), `verify_embedding_reranker_settings.sh`, `verify_embedding_reranker_ui.py`, `verify_bundled_immutability.sh` | Verify against front-door |

## Dependencies

- Folder A (pins): `BOOFINITY_VERSION`, `LLAMA_SWAP_VERSION`, llama.cpp bump.
- Folder B (topology): `hlh_swap:9620` front-door, `hlh_infer` boofinity service,
  `hlh_infer_cache` volume at `/cache` with `HF_HOME=/cache` + `HF_HUB_OFFLINE=1`,
  and the served aliases `qwen3-embed` / `qwen3-reranker` routed by llama-swap.
  Folder B already removed the embed/rerank sections from `models.ini`; this
  folder must deploy **with or after** B so the aliases resolve at the
  front-door rather than 404 on `hlh_chat`.

## Out of scope

- Qwen3-VL embed/rerank retrieval and the image-embedding `vector(1024)` index
  (folder D).
- The `hlh_swap` / `hlh_infer` compose services and the swap config (folder B).
- The `BOOFINITY_VERSION` / `LLAMA_SWAP_VERSION` pins themselves (folder A).
- Any change to the 1024-dim contract: boofinity embeddings are still 1024-dim,
  so the verbatim wire-string in `providers.py` is preserved unchanged.
- Schema changes. The reingest-trigger guard is a `global_settings` key/value
  row, not a new column.

## Risk

Moderate. Two risks dominate (detailed in design.md):

- **Reingest auto-trigger safety.** Firing `reingest-all` automatically must be
  exactly-once and crash-safe. A re-fire on every boot would re-embed the entire
  corpus repeatedly; a fire mid-pull (before boofinity weights are `ready`)
  would re-embed against a down backend and mark every source `error`. The
  guard is a `global_settings` sentinel plus a readiness precondition.
- **GGUF -> safetensors numerical drift.** The old and new embedders are both
  Qwen3-Embedding-0.6B by name, but Q8_0 GGUF (llama.cpp pooling) and fp32
  safetensors (boofinity pooling) produce different vectors. Stored vectors
  retrieved against a new query vector silently degrade until reingest
  completes; the cutover trigger plus a Settings "retrieval is rebuilding"
  banner make the rebuild visible rather than silent.
