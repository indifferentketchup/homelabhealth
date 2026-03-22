# BourBites 3.0 — Project Context
Last updated: March 2026

## Location
- Stack: `/opt/bourbites3/` on ubuntu-homelab (`100.114.205.53`)
- Public URL: `https://bourbites.boogaardmusic.com`
- Backend API: `100.114.205.53:8600` (container: `bourbites_api`)
- Frontend nginx: `100.114.205.53:8601` (container: `bourbites_ui`)
- Database: `bourbites_db` (Postgres 16, internal Docker network only)

## Docker
- Compose file: `/opt/bourbites3/docker-compose.yml`
- Network: `bourbites_net` (internal bridge)
- Volumes: `bourbites3_bourbites_db_data` (Postgres), `bourbites3_bourbites_branding` (branding assets)
- Env: `/opt/bourbites3/.env`

## Frontend
- Vanilla HTML/CSS/JS — **no build step**
- Files at `/opt/bourbites3/frontend/` — editable live, changes show on page refresh
- JS modules (load order):
  `iconpicker.js` → `api.js` → `state.js` → `branding.js` → `workspaces.js` → `sidebar.js` → `docs.js` → `todos.js` → `projects.js` → `calendar.js` → `settings.js` → `ui.js` → `app.js`
- To edit files directly: File Browser at `files.boogaardmusic.com`

## Backend
- FastAPI + asyncpg, Python 3.12
- Source at `/opt/bourbites3/backend/`
- Schema auto-runs on startup from `schema.sql`
- **Requires rebuild** (`docker compose build bourbites-api && docker compose up -d`) for any backend Python changes
- `caldav_sync.py` handles all Baikal CalDAV operations
- `branding.py` handles all branding config (stored in Docker volume as `config.json`)

## CalDAV
- Baikal at `100.114.205.53:5232` (container: `baikal`, `/opt/baikal/`)
- `CALDAV_URL` must be `http://100.114.205.53:5232/dav.php` (NOT the public URL)
- Three calendars: BourBites, SWK 6382 - Communities & Orgs, SWK 6575 - Diversity, Equity, Inclusivity
- `cal_names` param uses `|` as delimiter

## Deploy Pattern
```bash
# Frontend only (no rebuild needed):
sudo tar -xzf /tmp/deploy.tar.gz -C /opt/bourbites3/

# Backend changes (branding.py, main.py, schema.sql):
sudo tar -xzf /tmp/deploy.tar.gz -C /opt/bourbites3/
cd /opt/bourbites3 && docker compose build bourbites-api && docker compose up -d
```
Tar is always built with `tar -czf deploy.tar.gz -C <deploy_dir> .` so it extracts directly into `/opt/bourbites3/`.

## Branding System
- Config stored in Docker volume at `/data/branding/config.json` inside `bourbites_api`
- Endpoint: `GET/PUT /api/branding-api/config`
- `update_branding` merges `ws_config` patches (does not overwrite)
- `update_branding` returns URL-enriched config (bannerUrl, faviconUrl, sidebarBannerUrl)
- All visual customization persists here

### Branding fields (current)
Colors: `accentColor`, `accentBright`, `accentDim`, `goldColor`, `bgColor`, `bgPanel`, `bgCard`, `textColor`, `textDim`, `borderColor`
Typography: `fontSize`, `fontSizeContent`, `fontSizeSidebar`, `fontSizeHeading`, `fontFamily`
Assets: `title`, `subtitle`, `banner`, `sidebar_banner`, `favicon`, `icon`
Layout: `bannerHeight`, `sidebarWidth`, `listPanelWidth`, `listPanelFloat`
Icon sizes: `iconSizeRail`, `iconSizeWsCard`, `iconSizeSwitcher`, `iconSizeDocList`
Workspace header: `wsIconSize`, `wsFontSize`, `wsPadding`
Sidebar content: `sbIconSize`, `sbFontSize`, `sbRowHeight`, `sbPadding`
Workspace cards: `cardWidth`, `cardMinHeight`, `cardPadding`, `cardIconSize`, `cardIconAlign`, `cardNameSize`, `cardNameAlign`, `cardLayout` (`stacked`|`inline`), `cardShowTag`, `cardSectionCount`
Nav: `navLinks` (array of `{view, label, icon, hidden}`), `editMode`

## Workspace Schema
```sql
workspaces (
  id, name, emoji, tag, color, description,
  hidden BOOLEAN DEFAULT FALSE,
  ws_config JSONB DEFAULT '{}',  -- merged via PATCH, never overwritten
  sort_order, created_at
)
```
- `ws_config.sections`: `{docs, todos, calendar, projects}` booleans
- `ws_config.pinned`: array of `{type, id, title}`
- `icon_url`: set via `POST /workspaces/{id}/icon`

## Navigation / State
- `S.navLinks`: array of `{view, label, icon, hidden}` — drives both rail and sidebar Navigate
- `S.editMode`: boolean — shows inline sidebar edit toolbar + rail overlays
- `S.branding`: full branding config object
- Rail buttons: `docs`, `notes`, `todos`, `projects`, `calendar`, `folders`, `collections`, `tags` (Settings ⚙️ is locked, not editable)

## Landing Page (Home View)
- `renderLanding()` in `docs.js` — single definition at top of file
- Cards show collapsible sections per workspace: Recent Docs, Todos (upcoming by due date), Calendar (next 30 days), Active Projects
- Section state persisted in `localStorage` key `bb-sec-{wsId}-{sectionKey}`
- Pinned items stored in `ws_config.pinned`, shown at top of card
- Right-click card: Change Icon, Edit (name/tag), Description, Sections config, Hide/Show
- Workspace visibility: `hidden` field on workspace — hidden workspaces don't appear on landing

## Icon Picker
- `iconpicker.js` loads first — `renderIconStr(iconStr, size?)` and `openIconPicker(callback, anchorEl)` available globally
- Two tabs: Emoji (default), Material Icons Filled
- `renderIconStr` with no size: no inline style, CSS cascade applies
- Card icons use dedicated classes: `.ws-card-emoji-char`, `.ws-card-mi-icon`, `.ws-card-icon-img` — all read `--card-icon-size` CSS var directly
- Material Icons loaded from jsDelivr CDN in `index.html`

## Editor (Current State)
- `renderDocEditor(id)` in `docs.js`
- Plain `<textarea class="content-area">` — raw markdown, no preview, no toolbar formatting buttons
- Monospace font (`JetBrains Mono` / `Fira Code`)
- **Markdown rendered preview not implemented** — next task

## Settings Page Sections (in order)
1. Branding (title, subtitle, banner, sidebar banner, banner height, favicon)
2. Colors (9 color pickers with hex inputs)
3. Typography (font size slider, font family select)
4. Layout (nav panel width, list panel width, list panel float toggle)
5. Font Sizes (content, sidebar, headings)
6. Workspace Cards (layout, width, min-height, padding, icon size/align, name size/align, show tag, items per section)
7. Workspace Header (icon size, name font, padding)
8. Sidebar Content (icon size, font size, row height, side padding)
9. Icon Sizes (rail nav, workspace cards, sidebar switcher, doc list)
10. Edit Mode (enable toggle)
11. Navigation Links (drag reorder, icon picker, rename, hide/show)
12. Workspaces (icon upload, rename+tag modal, sections config, hide/show, delete)

## API Endpoints (notable)
- `GET/PATCH /workspaces/{id}` — PATCH merges ws_config
- `POST /workspaces/{id}/icon` — upload workspace icon
- `GET /workspaces/{id}/docs?limit=N&sort=updated_at`
- `GET /workspaces/{id}/todos`
- `GET /workspaces/{id}/projects`
- `GET /calendar?workspace_ids=...&start=...&end=...`
- `GET/PUT /branding-api/config`
- `POST /branding-api/upload/{banner|sidebar_banner|favicon|icon}`
- `GET /context` — BeanAI doc dump

## Known Issues / To Do
- Markdown rendered preview not implemented (next task)
- Calendar event edit/delete not implemented (backend endpoints missing)
- Agenda view timezone cutoff — events stored as CST show as next-day UTC
- Doc-to-doc linking not implemented
- Download attached files not implemented
- Bulk copy-to and bulk assign due date not implemented
- `update_branding` `sidebarBannerUrl` enrichment — `sidebar_banner` key may not match
- Nav link defaults may flash before branding `navLinks` loads
- Bourbites session cookie → persistent auth solution needed (blocks Tweak context.py wiring)
- Bourbites RAG blocked until docs populated

## Preferences
- Terminal: Termius (already connected — never provide `ssh user@host` commands)
- Caddy config: `sed`/`tee` commands only, never manual copy-paste, always reload after
- File edits: prefer `sed`, `tee`, or `sudo python3` one-liners
- Backups before any destructive step
- Direct, no fluff, commands first
- `docker compose` (v2 plugin) on ubuntu-homelab
