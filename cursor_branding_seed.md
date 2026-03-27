# boolab — Branding Asset Seeding

## Task
Commit default branding assets to the repo and seed them into the DB + volume on API startup. Also seed default personas from JSON sidecars.

---

## 1. Repo Structure

```
backend/
  assets/
    booops/
      banner.png
      icon.png
      logo.png
      og_banner.png
    808notes/
      banner.png
      icon.png
      logo.png
      og_banner.png
    boolab/
      banner.png
      icon.png
      logo.png
      og_banner.png
    personas/
      booops-logo.png
      808notes-logo.png
      tweak-logo.png
      booops-logo.json
      808notes-logo.json
      tweak-logo.json
```

---

## 2. Persona JSON Sidecar Format

**`booops-logo.json`**
```json
{
  "name": "BooOps",
  "emoji": "🤖",
  "mode": "booops",
  "system_prompt": "You are BooOps, a generalist AI assistant. You are direct, pragmatic, and science-first. You help with anything — coding, writing, research, problem-solving. No fluff, no filler. Get to the point."
}
```

**`808notes-logo.json`**
```json
{
  "name": "808notes",
  "emoji": "🎵",
  "mode": "808notes",
  "system_prompt": "You are 808notes, a school-focused AI assistant. You are pragmatic and efficient. You help with academic writing, research, course assignments, and study tasks. Prioritize clarity and correctness. No padding."
}
```

**`tweak-logo.json`**
```json
{
  "name": "Tweak",
  "emoji": "🐾",
  "mode": "booops",
  "system_prompt": "You are Tweak, a snarky, science-first AI assistant. You are pragmatic and direct. You help with whatever comes up — but you have opinions and you're not afraid to share them."
}
```

---

## 3. Seeding Logic — `backend/seed_assets.py`

Create a new file `backend/seed_assets.py` with a single async function `seed_default_assets()`. Call it from `main.py` lifespan after the DB pool is ready.

### Branding Seed

For each mode (`booops`, `808notes`, `boolab`) and each slot (`banner`, `logo`, `icon`, `og_banner`):

- Check DB: `SELECT config FROM branding_config WHERE mode = $1`
- For each slot, if `{slot}Url` is empty or missing in stored config:
  - Source: `backend/assets/{mode}/{slot}.png` (use `Path(__file__).parent` for resolution)
  - Dest: `BRANDING_ASSETS_DIR / f"{mode}_{slot}.png"` (use the existing constant from `routers/branding.py`)
  - Copy file
  - Set URL to `/api/branding/{mode}/asset/{slot}`
  - Patch DB via the existing `_persist_{mode}_patch` helpers (import from `routers.branding`)
- **Slot → URL key mapping** (handle explicitly — do not derive automatically):
  - `banner` → `bannerUrl`
  - `logo` → `logoUrl`
  - `icon` → `faviconUrl`
  - `og_banner` → `ogBannerUrl`

### Persona Seed

For each `.json` file in `backend/assets/personas/`:

- Parse JSON (`name`, `emoji`, `mode`, `system_prompt`)
- Check `personas` table: `SELECT id FROM personas WHERE name = $1`
- If not exists: insert into `personas` with those fields + `is_default = false`
- Find matching `.png` (same stem) in `backend/assets/personas/`
- Copy to `BRANDING_ASSETS_DIR / f"persona_{stem}.png"`
- Update `personas` row: set `avatar_url = /api/branding/persona/asset/{stem}`

> Check `schema.sql` for exact column names before writing the insert. Match exactly.

---

## 4. Asset Serving Endpoints

Add to `routers/branding.py`:

```python
@router.get("/persona/asset/{stem}")
async def get_persona_asset(stem: str):
    path = BRANDING_ASSETS_DIR / f"persona_{stem}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="image/png")


@router.get("/assets/library")
async def list_asset_library():
    """Return all committed default assets available for use in personas, branding, etc."""
    _ensure_assets_dir()
    src = Path(__file__).parent.parent / "assets"
    library = {}
    for mode_dir in sorted(src.iterdir()):
        if not mode_dir.is_dir():
            continue
        library[mode_dir.name] = [
            f"/api/branding/assets/library/{mode_dir.name}/{f.name}"
            for f in sorted(mode_dir.iterdir())
            if f.suffix.lower() in ALLOWED_IMG_EXT
        ]
    return library


@router.get("/assets/library/{mode}/{filename}")
async def serve_library_asset(mode: str, filename: str):
    src = Path(__file__).parent.parent / "assets" / mode / filename
    if not src.is_file():
        raise HTTPException(status_code=404, detail="not found")
    media_type, _ = mimetypes.guess_type(str(src))
    return FileResponse(src, media_type=media_type or "application/octet-stream")
```

`GET /api/branding/assets/library` returns a dict of all committed assets — use this to populate image pickers when creating personas, DAWs, or branding slots.

---

## 5. `main.py` Lifespan

After pool init, add:

```python
from seed_assets import seed_default_assets
await seed_default_assets()
```

---

## 6. Constraints

- `ON CONFLICT DO NOTHING` or existence check before all inserts — never duplicate
- If an asset file is missing from the repo, skip silently (log a warning, don't crash)
- Never hardcode `/data/branding/assets` — always use `BRANDING_ASSETS_DIR` from `routers/branding.py`
- Check `schema.sql` for exact personas column names before writing any insert
- `og_banner` → `ogBannerUrl` mapping must be explicit, not derived from the slot name

---

## 7. Verify

```bash
docker compose up --build -d
docker logs -f boolab_api
```

Logs should show seeding output. Then:

- `GET /api/branding/booops` → `bannerUrl`, `logoUrl`, `faviconUrl`, `ogBannerUrl` all populated
- `GET /api/branding/assets/library` → dict with all modes + file lists
- `GET /api/personas` → BooOps, 808notes, Tweak present with `avatar_url` set
