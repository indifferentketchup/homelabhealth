## REMOVED Requirements

### Requirement: frontend ai package
The `ai` (Vercel AI SDK) package SHALL NOT be declared as a frontend dependency.
**Reason**: Zero imports anywhere in `frontend/src/`. Never wired up.
**Migration**: None — no consumers exist.

#### Scenario: Build succeeds without ai package
- **WHEN** `ai` is absent from `package.json` and `npm run build` is executed
- **THEN** the build completes without missing-module errors

### Requirement: frontend next-themes package
The `next-themes` package SHALL NOT be declared as a frontend dependency.
**Reason**: Zero imports anywhere in `frontend/src/`. Local `useTheme` hook in ai-elements was not from this package; ai-elements is deleted.
**Migration**: None — no consumers exist.

#### Scenario: Build succeeds without next-themes
- **WHEN** `next-themes` is absent from `package.json` and `npm run build` is executed
- **THEN** the build completes without missing-module errors

### Requirement: frontend radix peer shadow entries
`@radix-ui/react-scroll-area` and `@radix-ui/react-tooltip` SHALL NOT be declared as direct frontend dependencies.
**Reason**: Both are re-exported by `radix-ui` (umbrella package), which is already a direct dep. No source file imports them directly.
**Migration**: None — `radix-ui` continues to provide these primitives transitively.

#### Scenario: ScrollArea and Tooltip components still render after removal
- **WHEN** the peer entries are removed and `npm install` is run
- **THEN** `npm run build` succeeds and the ScrollArea/Tooltip shadcn components import from `radix-ui` without error

### Requirement: frontend ai-elements orphan packages
Packages exclusively consumed by the deleted `ai-elements/` directory SHALL NOT remain as direct frontend dependencies.
**Reason**: `ai-elements/` was deleted in quick-wins-cleanup; no other consumers exist.
**Migration**: None — no consumers exist.

#### Scenario: Build succeeds after orphan removal
- **WHEN** each orphaned package is removed from `package.json` (after grep-confirming zero remaining imports) and `npm run build` is executed
- **THEN** the build completes without missing-module errors

### Requirement: backend huggingface-hub package
`huggingface-hub` SHALL NOT be declared in `backend/requirements.txt`.
**Reason**: Never imported as a Python module. `model_puller.py` uses HuggingFace URL strings only; downloads use `httpx`.
**Migration**: None — no consumers exist.

#### Scenario: Backend starts cleanly after removal
- **WHEN** `huggingface-hub` is absent from `requirements.txt` and the Docker image is rebuilt
- **THEN** `docker logs hlh_api` shows no import errors on startup
