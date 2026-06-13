# Product

## Register

product

<!-- Primary register is product (app UI). A public marketing/landing surface may come
     with a future public release; override register per-task when that work starts. -->

## Users

Self-hosters managing their own (and their family's/friends') personal health records on a home server. Technically capable enough to run a Docker stack, but using the app itself in a non-technical mode: uploading lab reports, medical PDFs, and photos, then asking plain-language questions about their health history. Context of use: at home, often during or after a medical event — reviewing results, preparing for an appointment, cross-referencing an old record. The emotional stakes are real; the interface meets people who may be anxious about what they're reading.

The job to be done: "get a grounded, trustworthy answer about my health records without handing them to a cloud service."

## Product Purpose

homelabhealth is a self-hosted RAG chat app for personal health records. Documents go in (PDF, images, lab tables via OCR and MedGemma vision), get chunked and embedded into pgvector, and a bundled local LLM answers questions grounded in those sources — with citations, safeguards, column encryption, de-identification, and a tamper-evident audit log. Everything runs locally in one Docker compose stack; no data leaves the machine.

Success looks like: a friend (non-author user) can install it with one command, upload their records, ask a question, and trust the answer — seeing exactly which source it came from.

## Brand Personality

**Calm, warm, trustworthy.** Reassuring and homey — the opposite of clinical institutional software. The interface should lower anxiety, not add to it: soft surfaces, generous type (18px base), unambiguous answers with visible sourcing. Warmth carries the brand, but it never undercuts seriousness — this is a tool people consult about their health, so confidence comes from clarity and provenance (citations, audit trail), not from decoration.

## Anti-references

- **Hospital portal / EHR** (MyChart, Epic): bureaucratic, dense, anxiety-inducing institutional software. No walls of tabular chrome, no buried actions behind nested menus.
- **Generic AI chat clone**: the undifferentiated ChatGPT-lookalike dark-SaaS chat shell with no domain identity. The chat surface must feel like a health companion, not a model playground.
- **Wellness-app pastel fluff** (Calm/Headspace register): decorative softness that undermines trust in medical answers. Warm ≠ cute; no illustration-heavy hand-holding.
- **Homelab dashboard aesthetic** (Grafana, Portainer): dark utilitarian ops-console density. The self-hosted plumbing stays backstage; the UI is a health tool, not an admin panel.

## Design Principles

1. **Provenance is the product.** Every answer shows where it came from. Citations, source panels, and safeguard/audit signals are first-class UI, never an afterthought — trust is built by showing the work.
2. **Calm under medical stress.** Users may arrive anxious. Prefer fewer, clearer elements over information density; errors and safeguard interventions are explained in plain language, never alarming or clinical.
3. **Readable by default.** Large base type (18px), AA contrast everywhere, line lengths capped for prose. If a choice trades elegance against legibility, legibility wins.
4. **The plumbing stays backstage.** Tiers, models, providers, and encryption are real complexity — surfaced fully in Settings for those who want it, invisible during everyday chat and upload flows.
5. **Warm, not soft on rigor.** The sage/cream/rose warmth signals "yours, at home"; the precision (exact lab values, verbatim error contracts, visible source text) signals "you can rely on this." Hold both.

## Accessibility & Inclusion

- **WCAG AA** is the working standard: ≥4.5:1 body text contrast (already enforced via documented token remediation in `globals.css`), ≥3:1 for large text and UI components.
- `prefers-reduced-motion` alternatives for all animation.
- Full keyboard navigability; visible focus rings (`--ring` token).
- Dark mode is a first-class theme (`class="dark"` on `<html>`), held to the same contrast bar.
- Streaming/loading states must remain legible to screen readers (announce completion, don't trap focus in the stream).
