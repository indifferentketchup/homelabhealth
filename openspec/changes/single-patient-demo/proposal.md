# Single-Patient Demo — First-Person Health Journal Rewrite

## Status

Active as of 2026-06-12.

- Implemented in the working tree: demo data rewrite, dead FHIR cleanup, `loadDemo` API wrapper, and demo CTA UI.
- Still remaining before archive: hide the demo CTA for non-admin users, run end-to-end stack verification, and decide whether frontend build warnings must be eliminated or accepted.

## TL;DR

Rewrite demo data from clinical lab/radiology reports into first-person health journal entries, add a frontend "Try Demo" button, and clean up dead FHIR code in the demo loader.

## Why

The current demo data is 12 `.txt` files formatted as professional clinical reports (Quest Diagnostics, LabCorp, radiology reports). These are doctor-oriented documents — third-person, dense with reference ranges, and written in clinical shorthand. They don't match the use case for a personal health RAG app, where users are expected to upload their own health journals, symptom logs, and plain-language summaries.

Rewriting these as first-person journal entries makes the demo feel authentic: a real person tracking their health over time. It also produces better RAG results — the chunked text will be in the same voice and format that real users upload.

The backend also has a dead `_fhir_bundle_to_text()` function (52 lines) from the pre-v1.2 era when FHIR JSON bundles were the demo format. No JSON files remain in demo_data. Removing this dead code simplifies the loader.

The frontend has no discoverable way to trigger demo data loading. Adding a "Try Demo" button on the landing page gives new users a one-click path to see the product in action.

## Scope

### In scope
- Rewrite 12 demo `.txt` files as 10 first-person health journal entries (same narrative: Alex Taylor, 1990 DOB, diabetes + iron deficiency + possible HAE)
- Remove `_fhir_bundle_to_text()` and JSON-handling code from `backend/routers/demo.py`
- Remove `import json` from demo.py (only used by dead FHIR code)
- Add `loadDemo` API wrapper to `frontend/src/api/workspaces.js`
- Add "Try Demo" button to WorkspaceLanding component (home page)
- Create openspec proposal.md, tasks.md, design.md

### Out of scope
- Changing the demo loader's ingest pipeline (it still uses the same `_ingest_source` path)
- Adding demo data for multiple patients
- Adding a "Clear Demo" button (the existing DELETE /api/demo/unload is sufficient for now)
- Internationalization of demo data

## Success criteria
- [x] 10 first-person journal entries in `backend/demo_data/` that feel authentic and personal
- [x] No FHIR-related code remains in `backend/routers/demo.py`
- [x] `import json` removed from demo.py (verified by grep)
- [ ] "Try Demo" button visible on landing page when no workspaces exist
- [ ] Clicking the button loads demo data and navigates to the Demo workspace chat
- [ ] Button handles loading state, error state, and already-exists state
- [x] openspec docs follow convention per `openspec/README.md`
