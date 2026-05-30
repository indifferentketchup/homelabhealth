# Remove MedSigLIP · MedGemma vision on-demand · 4b ingestion

**Date:** 2026-05-30
**Status:** Design (approved verbally; pending written review)
**Supersedes (partially):** `2026-05-28-smart-orchestra-bootstrap-design.md` — the
orchestra loses its runtime (vision-lifecycle) role and becomes bootstrap-only.

## Motivation

Three intertwined problems surfaced while debugging "vision not firing on
attached PNGs/JPGs":

1. **MedGemma vision was dead.** `services/vision.py:_call_vision` sends no
   `model` field, so under the llama-server **router** it `400`s and every image
   extraction silently falls back to poor OCR/parse text. And `models.ini`'s
   `[medgemma]` preset has no `mmproj` line, so even routing there loads MedGemma
   **without** the vision projector (image requests `500`). Net: images are never
   actually "read"; the chat only ever sees junk fallback text.

2. **MedSigLIP is unused weight.** The `hlh_vision_embed` sidecar (infinity-emb,
   MedSigLIP, 1152-dim image vectors) only powers explicit
   `/api/vision/{embed,search,classify}` endpoints — never the ingest or chat
   path. For a RAG **chat** app it earns nothing, and it drags in a ~5 GB sidecar,
   a Docker-socket-scoped orchestra lifecycle, schema/provider rows, puller
   entries, and frontend surface. Decision: **remove it entirely.**

3. **Ingestion vision should be cheap.** Image/PDF reading at ingest should run on
   **MedGemma-4b**, not the tier's 27b chat model. 4b (~3 GB + ~1 GB mmproj) stays
   fully **GPU-resident** alongside the 27b chat model on a 32 GB card, so nothing
   offloads to system RAM. Reading with 27b would force VRAM offload → slow.

## Decisions (settled with operator)

- **Remove MedSigLIP entirely** — runtime, infra, schema-wiring, frontend, docs.
- **Orchestra → bootstrap-only.** Drop the long-running FastAPI vision server and
  `/vision/*` endpoints; the orchestra image is now purely the `install.sh`
  `docker run -e HLH_BOOTSTRAP=1` bootstrap tool and **exits** when done.
- **MedGemma vision works on demand** via a dedicated router preset the router
  loads/evicts as needed.
- **Ingestion always uses MedGemma-4b**, tier-independent, for VRAM headroom.

## Part 1 — Remove MedSigLIP

Delete / unwire (no behavior left behind):

- **Backend code:** delete `services/vision_embed.py`, `services/vision_lifecycle.py`,
  `routers/vision_embed.py`. In `main.py` remove the `/vision` router mount and the
  `_vision_idle_evictor` task. Remove `resolve_vision_embed_provider` from
  `provider_client.py`. Remove vision_embed seeding/binding (`bundled_providers.py`)
  and `_check_vision_embed_sidecar` (`hlh/doctor.py`).
- **Model registry:** drop the `medsiglip` role from `ALL_ROLES` and
  `MODEL_REGISTRY` (`model_puller.py`); remove medsiglip from `model_inventory.py`.
- **Infra:** remove the `hlh_vision_embed` service and the `vision` compose profile
  from `docker-compose.yml`. In `bootstrap.py` remove `create_vision_embed`,
  `INFINITY_IMAGE`, the `hlh_vision_cache` volume, `HLH_ENABLE_VISION`, and
  `attach_self_to_network`. In `hlh_orchestra/app.py` remove the `/vision/*`
  endpoints and the FastAPI server; the entrypoint runs `bootstrap.run()` and exits.
- **Frontend:** remove vision-embed rows/state from `SystemTab.jsx` and
  `ModelStateSidebar.jsx`.
- **Docs/scripts:** delete `verify_a3_sidecar_split.sh`; prune references in
  `docs/`, `THREATMODEL.md`, `SECURITY.md`, `hlh-status.sh`, `.env.example`.

**Schema:** **keep** the `vision_embed` value in the `providers.role` CHECK
constraint. Removing an allowed enum value via idempotent ALTER is risky and buys
nothing — a never-inserted role value is harmless. Stop *seeding* the row; leave the
constraint permissive. (Documented so a future reader doesn't think it's a leak.)

## Part 2 — MedGemma vision on demand

- Add a `[medgemma-vision]` preset to **both** `hlh_chat/models.ini` and
  `hlh_orchestra/templates/models.ini` (they must mirror). It points at the 4b
  model + 4b mmproj (see Part 3) with `n-gpu-layers = auto`. The router loads it
  **on the first vision request** and evicts it after `sleep-idle-seconds` (1800).
- Fix `services/vision.py:_call_vision` to send `"model": "medgemma-vision"`.
- Safety: `is_vision_available()` (checks the mmproj file) already gates every call,
  so on a box without the vision model pulled the preset is **never requested** and
  cannot break chat. A separate preset (not `[medgemma]`) means the chat model is
  never affected by the mmproj.

## Part 3 — 4b ingestion vision (tier-independent)

- **Pull, always (when vision is enabled), regardless of chat tier:**
  `unsloth/medgemma-1.5-4b-it-GGUF` → `medgemma-1.5-4b-it-Q4_K_M.gguf` (base) +
  `mmproj-F16.gguf` (projector), landing at fixed paths under `/models/vision/`
  (e.g. `/models/vision/medgemma-4b.gguf`, `/models/vision/medgemma-4b-mmproj.gguf`).
- Rework the `vision` role in `MODEL_REGISTRY`: instead of a tier-keyed mmproj that
  switches to the 27b projector on big tiers, **always** supply the 4b base + 4b
  mmproj. (This is why a dedicated base-model pull is needed: on gpu-16gb/24gb+ the
  `chat` role pulls 27b, so the 4b GGUF isn't otherwise present.)
- `[medgemma-vision]` preset → `model = /models/vision/medgemma-4b.gguf`,
  `mmproj = /models/vision/medgemma-4b-mmproj.gguf`, `ctx-size = 8192`,
  `n-gpu-layers = auto`, `jinja = 1`.
- `vision.py:is_vision_available()` checks these fixed 4b paths.
- "Spot-check" == the existing two-pass extract (text + interpretation), just run on
  the 4b model. No new lighter mode. Applies to both `extract_image_via_vision` and
  `extract_pdf_via_vision`.

## Data flow (unchanged shape, fixed engine)

Upload image/PDF → `extract_*_via_vision` → `_call_vision(model="medgemma-vision")`
→ hlh_chat router loads 4b+mmproj on demand → returns text+interpretation → chunk →
embed (bge-m3 text) → `source_chunks`. Chat still consumes injected **text**; this
is not live multimodal chat (out of scope, below).

## Out of scope

- **Live multimodal chat** (model receives image pixels per chat turn). The app's
  design is extract-at-ingest-then-inject-text; that's preserved.
- **Image-similarity search / zero-shot classification** (the MedSigLIP features) —
  removed, not replaced.

## Deployment (operator pulls from GHCR + bootstrap one-liner)

1. Pull `hlh_api`, `hlh_ui`, `hlh_orchestra` `:latest`.
2. `docker rm -f hlh_search hlh_api hlh_ui hlh_chat` (so bootstrap recreates them
   with the new images + updated `models.ini`; `hlh_chat` must restart to reload the
   preset). Leave `hlh_db`.
3. Run the bootstrap one-liner (no `HLH_ENABLE_VISION` anymore). It overwrites
   `models.ini` in `hlh_config` and exits.
4. Pull the MedGemma-4b vision model from Settings → System (or the puller does it),
   landing the 4b base + mmproj under `/models/vision/`.
5. `hlh_vision_embed` (if it exists from a prior run) can be removed:
   `docker rm -f hlh_vision_embed`; `docker volume rm hlh_vision_cache`.

## Risks

- **Router VRAM juggling:** chat 27b + vision 4b both resident is fine on 32 GB; on
  smaller GPUs `models-max`/`sleep-idle` evict as needed (4b reloads quickly).
- **models.ini reload:** running llama-server won't re-read `models.ini` without a
  restart — deploy step 2 handles it via `docker rm -f hlh_chat`.
- **Puller size:** ingestion vision now pulls the 4b base even on 27b tiers
  (~2.5 GB extra). Acceptable; it's the cost of tier-independent cheap ingestion.
