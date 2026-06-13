# Tasks: dep-pruning

**Date:** 2026-06-12

---

## 1. Confirmed-dead frontend deps (never imported)

- [x] 1.1 Grep-confirm `ai` has zero imports: `grep -rn "from ['\"]ai['\"]" frontend/src/` must return no output.
- [x] 1.2 Remove `ai` from `dependencies` in `frontend/package.json`.
- [x] 1.3 Grep-confirm `next-themes` has zero imports: `grep -rn "next-themes" frontend/src/` must return no output.
- [x] 1.4 Remove `next-themes` from `dependencies` in `frontend/package.json`.

## 2. Redundant radix peer declarations

- [x] 2.1 Confirm `@radix-ui/react-scroll-area` is not imported directly: `grep -rn "react-scroll-area" frontend/src/` must return no output.
- [x] 2.2 Confirm `@radix-ui/react-tooltip` is not imported directly: `grep -rn "react-tooltip" frontend/src/` must return no output (tooltip.jsx imports from `"radix-ui"`, not this package).
- [x] 2.3 Remove `@radix-ui/react-scroll-area` and `@radix-ui/react-tooltip` from `dependencies` in `frontend/package.json`.

## 3. ai-elements orphans (sole consumer deleted)

For each package below, grep-confirm zero remaining imports, then remove from `package.json`. All greps run from repo root against `frontend/src/`.

- [x] 3.1 `@rive-app/react-webgl2`: `grep -rn "rive-app" frontend/src/` → 0 results → remove.
- [x] 3.2 `@streamdown/cjk`: `grep -rn "streamdown" frontend/src/` → 0 results → remove (covers all @streamdown/* and streamdown at once).
- [x] 3.3 `@streamdown/code`: remove (covered by 3.2 grep).
- [x] 3.4 `@streamdown/math`: remove (covered by 3.2 grep).
- [x] 3.5 `@streamdown/mermaid`: remove (covered by 3.2 grep).
- [x] 3.6 `streamdown`: remove (covered by 3.2 grep).
- [x] 3.7 `ansi-to-react`: `grep -rn "ansi-to-react\|Ansi" frontend/src/` → 0 results → remove.
- [x] 3.8 `media-chrome`: `grep -rn "media-chrome" frontend/src/` → 0 results → remove.
- [x] 3.9 `react-jsx-parser`: `grep -rn "react-jsx-parser\|JsxParser" frontend/src/` → 0 results → remove.
- [x] 3.10 `shiki`: `grep -rn "shiki" frontend/src/` → 0 results → remove.
- [x] 3.11 `tokenlens`: `grep -rn "tokenlens" frontend/src/` → 0 results → remove.
- [ ] 3.12 `embla-carousel-react`: `grep -rn "embla-carousel" frontend/src/` → 1 result (`carousel.jsx:3`). **STOP — consumer exists, do not remove.**
- [x] 3.13 `motion`: `grep -rn "from ['\"]motion" frontend/src/` → 0 results → remove.
- [x] 3.14 `@xyflow/react`: `grep -rn "xyflow" frontend/src/` → 0 results → remove.
- [x] 3.15 Packages with active consumers: `embla-carousel-react` (see 3.12). All others confirmed dead and already removed from package.json.

## 4. Backend dead dep

- [x] 4.1 Confirm `huggingface_hub` has zero Python imports: `grep -rn "from huggingface_hub\|import huggingface_hub" backend/` must return no output.
- [x] 4.2 Remove `huggingface-hub` from `backend/requirements.txt`.

## 5. Verification

- [x] 5.1 Run `cd frontend && npm install` to regenerate `package-lock.json`.
- [x] 5.2 Run `cd frontend && npm run build` — must complete with no missing-module errors.
- [x] 5.3 Run `python3 -m py_compile $(find backend -name '*.py')` — must return no errors.
- [x] 5.4 Run `docker compose up --build -d` and confirm `docker logs hlh_api` shows clean startup with no import errors.
- [x] 5.5 Update `CHANGELOG.md` under `[Unreleased]` with a Tooling entry summarizing removed deps.
