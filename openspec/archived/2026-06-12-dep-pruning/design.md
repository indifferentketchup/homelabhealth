## Context

Audit of `frontend/package.json` (38 runtime deps) and `backend/requirements.txt` (19 packages) found dead and redundant entries. The `quick-wins-cleanup` change also deleted `frontend/src/components/ai-elements/`, leaving 14 packages with no remaining consumer in the codebase.

Three categories:
1. **Never-imported deps** — declared but zero `import` statements anywhere (`ai`, `next-themes`, `huggingface-hub`)
2. **Redundant peer declarations** — `@radix-ui/react-scroll-area` and `@radix-ui/react-tooltip` are already re-exported by `radix-ui` (umbrella); the shadow entries in `package.json` are cargo-culted leftovers
3. **ai-elements orphans** — packages whose sole consumer (`ai-elements/`) was deleted; each requires a final grep to confirm no other file imports them before removal

## Goals / Non-Goals

**Goals:**
- Remove confirmed-dead packages from `package.json` and `requirements.txt`
- Update `package-lock.json` via `npm install`
- Confirm frontend build passes after removals
- Confirm backend compile-check passes after `requirements.txt` edit

**Non-Goals:**
- No behavior changes of any kind
- Not auditing transitive deps (only direct-dep entries in the manifest files)
- Not removing `react-markdown`/`remark-gfm` or `motion` (deferred — `react-markdown` still has active consumers in `MessageBubble.jsx`; `motion` deferred pending bundle-size evidence)

## Decisions

**Verify-then-remove workflow for ai-elements orphans.**
Each of the 14 orphaned packages must be independently grepped for imports across `frontend/src/` before removal. The ai-elements directory is gone but a package could have been imported elsewhere (e.g. a later feature added after the audit snapshot). Grep is the source of truth, not the audit snapshot.

**Remove redundant `@radix-ui/*` peer entries, keep `radix-ui`.**
The umbrella `radix-ui` package re-exports `ScrollArea` and `Tooltip` internally (confirmed: `node_modules/radix-ui/dist/index.js` lines 92, 103). Removing the peer entries from `package.json` does not remove the underlying packages — they stay as transitive deps of `radix-ui`. No breaking change.

**Backend: edit `requirements.txt` only — no pip uninstall.**
`huggingface-hub` removal is a manifest edit. The Docker image rebuild (`docker compose up --build`) installs from the updated `requirements.txt` cleanly; no in-container uninstall step is needed.

## Risks / Trade-offs

- **Radix peer version skew** → After removing `@radix-ui/react-scroll-area` and `@radix-ui/react-tooltip`, run `npm install` and check for peer warnings. `radix-ui` pins specific versions of its sub-packages; the removed explicit entries were likely redundant but not version-conflicting. Mitigation: `npm install` output is the signal; if warnings appear, re-add with the version `radix-ui` requires.
- **Stale audit snapshot for ai-elements orphans** → The audit ran before confirming each file's current state. Mitigation: grep each package immediately before removing it.
- **`package-lock.json` diff is large** → Expected. The lock file reflects the full transitive closure; removing 16+ direct deps cascades. No correctness risk — `npm install` regenerates it deterministically.

## Implementation notes

- **`embla-carousel-react` still has an active consumer** — `frontend/src/components/ui/carousel.jsx:3` imports `useEmblaCarousel from "embla-carousel-react"`. This package is NOT dead; it was excluded from the prior quick-wins-cleanup because `carousel.jsx` is still a live component. Do not remove.
- **`@xyflow/react` was successfully removed** — zero imports found in `frontend/src/`. Was previously in package.json.
- **`@radix-ui/react-scroll-area` and `@radix-ui/react-tooltip` removed** — confirmed no direct imports; `radix-ui` umbrella re-exports both.
