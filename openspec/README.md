# openspec

Per-batch documentation convention for homelabhealth, adopted v1.2.14.

**Agent entry point:** `CLAUDE.md` at repo root. **Architecture diagram:** `docs/architecture.md`. **Session bootstrap:** `docs/CONTEXT.md`.

Lift source: Fission-AI/OpenSpec directory layout. **No CLI dependency** — just the folder shape.

## Layout

```
openspec/
  changes/
    <slug>/                          # one folder per active planned/in-flight batch
      proposal.md                    # Why + scope summary
      tasks.md                       # numbered implementation step list
      design.md                      # architecture / data-model decisions (optional)
      specs/                         # reserved for future adoption
  archived/
    <slug>/                          # completed batches moved out of active work
  specs/                             # global specs, future use
```

## Conventions

- Slugs are lowercase-hyphenated derived from the batch title (e.g. `fork-lift-wave-1`, `safeguard-rewrite`).
- Each batch folder contains up to three files:
  - **`proposal.md`** — the "Why". Context, rationale, scope summary. Answers: why are we doing this, what problem does it solve, what is in scope and out of scope.
  - **`tasks.md`** — the action list. Numbered implementation steps with acceptance criteria and verification commands. This is what an agent executes.
  - **`design.md`** — architecture decisions worth recording separately. Data model changes, dependency ordering, guardrails, backward compat strategy. Optional for trivial batches.
- A canonical dispatch brief is naturally split as: `proposal.md` (context + rationale) + `tasks.md` (scope items, build + verify) + `design.md` (architecture decisions).
- Active work lives in `openspec/changes/<slug>/`. Once a batch is implemented and its docs are no longer the active execution plan, move it to `openspec/archived/<slug>/`.
- Already-shipped pre-convention work is not retroactively split into proposal/tasks. New batches land directly in `changes/<slug>/`.
