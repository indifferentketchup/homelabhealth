# Impulse — Context Doc
Last updated: March 2026

## Overview
Personal health + accountability tracker. Self-hosted on ubuntu-homelab. Dark PWA. Tracks hygiene, sleep, water, steps, dog walks, music, energy drinks, fast food, mood, and school assignments via CalDAV sync.

**Public URL:** `https://impulse.boogaardmusic.com`  
**Slogan:** track the damage.

---

## Infrastructure

| Component | Location |
|---|---|
| Container | `impulse` on ubuntu-homelab (`100.114.205.53`) |
| Port | `100.114.205.53:8520` |
| Compose file | `/opt/impulse/docker-compose.yml` |
| Frontend | `/opt/impulse/frontend/` (mounted read-only into container) |
| Database | SQLite at `/data/impulse.db` inside `impulse_data` Docker volume |
| Reverse proxy | Caddy on droplet (`161.35.250.151`), block in `/opt/caddy/Caddyfile` |

### Deploy pattern
```bash
sudo tar -xzf /tmp/impulse_vN.tar.gz -C /opt/impulse
CALDAV_PASS=$(grep CALDAV_PASS /opt/bourbites3/.env | cut -d= -f2) docker compose -f /opt/impulse/docker-compose.yml up -d --build
```

**Critical:** `CALDAV_PASS` must be passed as a shell env var — never stored in `.env` (gets overwritten on deploy). Password lives in `/opt/bourbites3/.env`.

Frontend-only changes: no `--build` needed, just `up -d`.

---

## Stack

- **Backend:** FastAPI + uvicorn, Python 3.12, SQLite via stdlib `sqlite3`
- **Frontend:** Vanilla HTML/CSS/JS, no build step. Changes live-reload on page refresh.
- **Charts:** Chart.js 4.4.4 via CDN
- **Fonts:** Space Mono (mono/labels), DM Sans (body) via Google Fonts
- **PWA:** `manifest.json` + `sw.js` (network-first, no aggressive caching)

---

## Environment Variables

| Var | Value |
|---|---|
| `DB_PATH` | `/data/impulse.db` |
| `FRONTEND_PATH` | `/app/frontend` |
| `CALDAV_URL` | `http://100.114.205.53:5232/dav.php` |
| `CALDAV_USER` | `samkintop` |
| `CALDAV_PASS` | from shell env, sourced from BourBites `.env` |
| `CALDAV_CALENDARS` | `swk6382\|swk6575\|84c91a84-228a-11f1-89a8-56615c642ed7` |

---

## Database Schema

### `log`
Daily entries for all self-care tracking.
```sql
id, date TEXT, key TEXT, value TEXT, meta TEXT
UNIQUE(date, key, meta)
```
Key/value patterns:
| key | value | meta |
|---|---|---|
| `teeth_am` | `1`/`0` | null |
| `teeth_pm` | `1`/`0` | null |
| `shower_am` | `1`/`0` | null |
| `shower_pm` | `1`/`0` | null |
| `music` | `1`/`0` | null |
| `sleep` | hours float (legacy) | null |
| `bed_time` | `HH:MM` | null |
| `wake_time` | `HH:MM` | null |
| `water` | integer (glasses) | null |
| `steps` | integer | null |
| `dog_walks` | integer | null |
| `mood` | comma-separated mood card IDs | null |
| `notes` | free text | null |
| `energy` | count integer | `ProductName\|size/flavor` |
| `ff` | count integer | `PlaceName\|` |

### `mood_cards`
```sql
id, emoji TEXT, name TEXT, valence REAL, arousal REAL
```
23 default cards. Valence: -2 (negative) to +2 (positive). Arousal: -2 (low energy) to +2 (high energy).

### `energy_products`
```sql
id, name TEXT UNIQUE, emoji TEXT, sizes TEXT (JSON array), active INTEGER
```
Defaults: Monster (16/19/24oz), 5-hour Energy (Extra Strength), Red Bull (12/16/20oz).

### `fastfood_places`
```sql
id, name TEXT UNIQUE, emoji TEXT, active INTEGER
```
Defaults: McDonald's, Culver's, Taco Bell, Wendy's, Chipotle, Chick-fil-A.

### `assignments`
```sql
id, uid TEXT UNIQUE, title TEXT, due_date TEXT, calendar TEXT, submitted_date TEXT
```
Synced from Baikal CalDAV. `uid` = CalDAV UID (may have `_todo` suffix for converted VTODO items). `submitted_date` set manually via Submit button.

### `ui_settings`
```sql
key TEXT PRIMARY KEY, value TEXT
```
Not yet fully implemented. Reserved for UI customization (width, colors, fonts).

---

## Backend API Endpoints

### Daily Log
| Method | Path | Description |
|---|---|---|
| GET | `/api/log/{date}` | All entries for a date |
| POST | `/api/log` | Upsert entry `{date, key, value, meta?}` |
| DELETE | `/api/log?date=&key=&meta=` | Delete entry |
| GET | `/api/history?key=&days=` | History for a key |
| GET | `/api/history/range?start=&end=` | All entries in date range |

### Steps (Apple Health Shortcut)
| Method | Path | Description |
|---|---|---|
| POST | `/api/steps` | `{date: "YYYY-MM-DD", steps: int}` |

### Mood Cards
| Method | Path | Description |
|---|---|---|
| GET | `/api/mood-cards` | All cards |
| POST | `/api/mood-cards` | Add card `{emoji, name, valence, arousal}` |
| DELETE | `/api/mood-cards/{id}` | Delete card |

### Energy Products
| Method | Path | Description |
|---|---|---|
| GET | `/api/energy-products` | Active products |
| POST | `/api/energy-products` | Add `{name, emoji, sizes}` |
| DELETE | `/api/energy-products/{id}` | Soft-delete (sets active=0) |

### Fast Food Places
| Method | Path | Description |
|---|---|---|
| GET | `/api/fastfood-places` | Active places |
| POST | `/api/fastfood-places` | Add `{name, emoji}` |
| DELETE | `/api/fastfood-places/{id}` | Soft-delete |
| GET | `/api/fastfood/streaks` | Days since last visit, global + per place |

### School / CalDAV
| Method | Path | Description |
|---|---|---|
| GET | `/api/school/assignments` | Sync from CalDAV + return all (≤ TERM_END) |
| POST | `/api/school/assignments/{uid}/submit` | `{submitted_date: "YYYY-MM-DD"}` |
| DELETE | `/api/school/assignments/{uid}/submit` | Unsubmit |
| GET | `/api/school/calendars` | Debug: list Baikal calendar hrefs |

---

## Frontend JS Modules

Load order in `index.html`:
```
api.js → school.js → today.js → trends.js → settings.js → app.js
```

All scripts have `?v={timestamp}` cache-busting query strings. Update timestamp on every deploy that changes JS.

### `api.js`
Global API wrapper. All functions return JSON. Key globals:
- `API` object with all endpoint methods
- `toast(msg, dur)` — shows bottom toast
- `todayStr()` — returns `YYYY-MM-DD` for today
- `formatDate(str)` — human-readable date
- `last90Days()` — array of date strings

### `app.js`
Entry point. Wires nav tabs (both `#top-nav` for desktop and `#bottom-nav` for mobile). `switchView(view)` is the main navigation function. Banner click → today.

### `today.js`
Self Care view. Key globals:
- `todayDate` — currently viewed date (navigable)
- `todayTab` — active tab: `all|hygiene|consumption|mood|notes`
- `logCache` — flat object of today's log entries
- `renderToday()` — full re-render
- `loadTodayResources()` — fetches mood cards, energy products, fastfood places

Sleep is tracked as `bed_time` + `wake_time` (HH:MM), hours derived client-side via `calcSleepHours()`.

Energy drink entries use `meta = "ProductName|size"` as the unique key.  
Fast food entries use `meta = "PlaceName|"`.

### `school.js`
School view + trend helpers. Key globals:
- `assignmentsCache` — array of assignment objects
- `schoolType` — `discussion|assignment|bourbites`
- `schoolRange` — `this_week|next_week|upcoming|previous`
- `schoolWeekOffset` — int, week navigation offset

**Calendar UUID map:**
| Calendar | ID | Color | Label |
|---|---|---|---|
| SWK 6382 | `swk6382` | `#a78bfa` (purple) | SWK 6382 |
| SWK 6575 | `swk6575` | `#f5a623` (orange) | SWK 6575 |
| BourBites | `84c91a84-228a-11f1-89a8-56615c642ed7` | `#34d399` (green) | BourBites |

**Tab logic:**
- Discussions tab = events where `isDiscussion(a)` = `CATEGORIES:Discussion` or Thursday
- Assignments tab = non-discussion, non-BourBites events
- BourBites tab = BourBites UUID calendar only

**Term end:** `2026-05-08` — backend filters out anything after this date.

### `trends.js`
Trends view. Key globals:
- `trendsTab` — `habits|metrics|mood|consumption|school`
- `trendsDays` — int (7/14/30/60/90/180/365/9999)

Data start date for orange indicator: `2026-03-19`.

Charts use Chart.js 4. Start-date line uses `meta.data[idx].x` (not `getPixelForIndex` which doesn't exist in v4).

### `settings.js`
Settings view. Currently has sub-sections for mood cards, energy products, fast food places, and Apple Health Shortcut instructions. Full settings overhaul (UI customization, data editing, calendar management) is pending.

---

## CalDAV Notes

- Baikal at `http://100.114.205.53:5232/dav.php` (internal only — public URL hits nginx root, returns 405)
- Both VEVENT and VTODO queries are fired; VTODO parser appends `_todo` to uid
- Events converted to floating time (`DTSTART:YYYYMMDDTHHmmss` no Z, no TZID) to avoid UTC offset issues in Thunderbird
- Monday assignments were originally stored as UTC 04:59 next day — fixed by subtracting 1 day from all Monday events
- CATEGORIES field: `Discussion` for Thursday events and May 6, `Assignment` for everything else

### CalDAV manipulation scripts (saved in `/tmp/` on homelab)
- `fix4.py` — subtract 1 day from Monday events
- `fix5.py` — set CATEGORIES:Discussion on Thursday + May 6 events

---

## Nav Structure

```
Desktop (≥768px): banner → #top-nav → #main → (no bottom nav)
Mobile (<768px):  banner → #main → #bottom-nav
```

Tabs: SELF CARE 🤟 | SCHOOL 📚 | TRENDS 📈 | SETTINGS ⚙️

---

## PWA / Icons

| File | Size | Use |
|---|---|---|
| `icons/icon-192.png` | 192×192 | PWA install icon |
| `icons/icon-512.png` | 512×512 | PWA splash |
| `icons/favicon.ico` | 32×32 | Browser tab |
| `icons/banner.png` | 680×226 | Site banner |
| `icons/og-banner.jpg` | 1200×630 | OG/Twitter card |

OG title: "Impulse: track the damage"

---

## Apple Health Shortcut (Steps)

POST to `https://impulse.boogaardmusic.com/api/steps`:
```json
{"date": "YYYY-MM-DD", "steps": 12345}
```
Build in iOS Shortcuts: Get My Steps → Get Contents of URL (POST, JSON body). Automate daily.

---

## Known Issues / Pending

- Settings overhaul not built: UI customization (width, font, colors), data editor (edit/delete by day), calendar settings page
- Trends mobile swipe partially broken
- BourBites calendar events not showing in School (UUID syncs but needs resync after clearing DB)
- `update_branding` / UI settings endpoint not fully wired to frontend
- No soft-delete or archive for log entries — only hard delete via API
