## Why

The dependency audit identified dead and redundant entries in `frontend/package.json` and `backend/requirements.txt`. Additionally, the `quick-wins-cleanup` change deleted `frontend/src/components/ai-elements/`, leaving behind every package that was its exclusive consumer. These should be removed now before they accumulate transitive peers, inflate Docker image layers, and mislead future dependency audits.

## What Changes

- **Remove dead frontend deps (never imported):** `ai`, `next-themes`
- **Remove redundant peer declarations:** `@radix-ui/react-scroll-area`, `@radix-ui/react-tooltip` — already re-exported by `radix-ui` (umbrella), which is a direct dep; the individual packages add nothing
- **Remove ai-elements orphans (sole consumer deleted):** `@rive-app/react-webgl2`, `@streamdown/cjk`, `@streamdown/code`, `@streamdown/math`, `@streamdown/mermaid`, `ansi-to-react`, `media-chrome`, `react-jsx-parser`, `streamdown`, `shiki`, `tokenlens`, `embla-carousel-react`, `motion`, `@xyflow/react` — all confirmed used only within `ai-elements/`; verify each before removal
- **Remove dead backend dep:** `huggingface-hub` — never imported as a Python module; all HuggingFace downloads use `httpx` directly
- Run `npm install` after frontend removals to update `package-lock.json`; run `pip install` / Docker rebuild for backend

## Capabilities

### New Capabilities

None. This change removes dead weight; it introduces no new runtime behavior.

### Modified Capabilities

None. No spec-level behavior changes — these deps have no active consumers.

## Impact

- `frontend/package.json`: up to 16 packages removed from `dependencies`
- `frontend/package-lock.json`: regenerated (smaller)
- `backend/requirements.txt`: 1 package removed
- Docker image size: reduced (fewer pip-installed packages)
- No API surface changes, no schema changes, no runtime behavior changes
