# Dashgaard — Context
Last updated: March 2026

## What it is
Custom homelab dashboard. Replaces Dashy. Shows all self-hosted services grouped by category with live uptime status pulled from Uptime Kuma. Fully self-contained — no external dependencies at runtime.

## Location
- Container: `dashgaard` on `ubuntu-homelab` (`100.114.205.53`)
- Port: `8094` (host) → `3000` (container)
- Compose: `/opt/dashgaard/docker-compose.yml`
- Data volume: `/docker/dashgaard/data` → `/data` inside container
- Public URL: not yet proxied (`dashgaard.boogaardmusic.com` Caddy block pending)

## Stack
- **Backend**: Node 20 / Express — serves static frontend + REST API
- **Frontend**: Single `index.html` — vanilla HTML/CSS/JS, no build step, baked into image
- **Config**: `/data/config.json` (persisted in Docker volume, survives rebuilds)
- **Icons/Assets**: `/data/` (served via `/uploads/*`)

## Config structure (`config.json`)
```
{
  site: { title, slogans[], banner, logo, favicon },
  uptime: { url, slug, enabled },
  theme: { fontBody, fontMono, fontDisplay, cardSize, accentColor, bgColor, cardBg,
           textColor, pageMaxWidth, baseFontSize, cardGap, cardRadius, heartbeatHeight,
           cardIconSize, cardNameSize, cardJustify, cardValign, cardDirection },
  mobile: { cols, cardDirection, cardJustify, cardValign, cardIconSize, cardNameSize, showDesc },
  groups: [
    { id, name, order, services: [
      { id, name, url, icon, description, color, order }
    ]}
  ]
}
```
Config is read on every request (`GET /api/config`), written atomically on save (`PUT /api/config`). Default config is seeded on first boot if `/data/config.json` doesn't exist.

## API endpoints
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/config` | Full config read |
| PUT | `/api/config` | Full config write (replaces) |
| GET | `/api/uptime/:slug` | Proxy to Uptime Kuma status-page + heartbeat API |
| POST | `/api/upload?slot=banner\|logo\|favicon` | Upload image, optionally set site slot |
| GET | `/api/uploads` | List uploaded icon files |

Static routes: `GET /` → `frontend/index.html`; `GET /uploads/*` → `/data/` (icons etc.)

## Assets
| File | Host path | Served at |
|---|---|---|
| favicon | `/docker/dashgaard/data/favicon.png` | `/uploads/favicon.png` |
| logo | `/docker/dashgaard/data/logo.png` | `/uploads/logo.png` |
| banner | `/docker/dashgaard/data/banner.png` | `/uploads/banner.png` |
| OG image | `/docker/dashgaard/data/og-banner.png` | `/uploads/og-banner.png` |
| PWA manifest | `/docker/dashgaard/data/manifest.json` | `/uploads/manifest.json` |

## Frontend architecture
Single `index.html`. No modules, no bundler. Key JS functions:
- **`applyTheme(t)`** — reads `config.theme`, sets CSS vars on `:root`
- **`applyMobileStyles()`** — runs on mobile only (`window.innerWidth <= 600`), applies `config.mobile` settings (cols, direction, alignment, sizes). Called after `render()` on boot, pollUptime, and saveSettings.
- **`render()`** — fetches `/api/config`, builds card grid
- **`buildCard(svc, status, idx)`** — constructs `.card` DOM element
- **`renderSettingsTab(tab)`** — renders settings panel tab content
- **`renderMobileTab()`** — Mobile settings tab (columns, direction, alignment, icon/name size, show desc)
- **`collectMobileSettings()`** — reads mobile tab inputs into `pendingCfg.mobile`
- **`saveSettings()`** — collects all tabs → `PUT /api/config` → `render()` → `applyMobileStyles()` → `closeSettings()`
- **`pollUptime()`** — fetches uptime data every 60s, updates status badge + re-renders

Settings panel tabs: Site | Theme | Services | Uptime | Mobile

## Card system
Cards live inside `.card-grid` (CSS grid). Layout controlled by CSS vars from `config.theme` on desktop, overridden by `applyMobileStyles()` on mobile using `config.mobile`.

### CSS vars controlling card layout
| Var | Default | Controlled by |
|-----|---------|---------------|
| `--card-icon-size` | `2rem` | Theme: Card Icon Size / Mobile: Card Icon Size |
| `--card-name-size` | `15px` | Theme: Card Name Font Size / Mobile: Card Name Font Size |
| `--card-justify` | `flex-start` | Theme/Mobile: Card Content Alignment |
| `--card-text-align` | `left` | Derived from `--card-justify` |
| `--card-valign` | `flex-start` | Theme/Mobile: Card Vertical Alignment |
| `--card-direction` | `row` | Theme/Mobile: Card Layout Direction |
| `--card-gap` | `10px` | Theme: Card Gap slider |
| `--card-radius` | `10px` | Theme: Card Border Radius slider |

## Mobile layout
- Media query at `max-width:600px` handles base responsive CSS
- `config.mobile.cols`: `'1'` (default) or `'2'` — sets `grid-template-columns` inline on `.card-grid` elements
- `config.mobile.showDesc`: hides `.card-desc` on mobile when false
- Status badge moved inline with Edit/Settings buttons in header-actions on mobile
- `applyMobileStyles()` must be called after every `render()` on mobile — inline styles override the CSS `grid-template-columns:1fr` rule

## Uptime Kuma integration
Backend proxies to Uptime Kuma at `UPTIME_KUMA_URL` (default `http://100.114.205.53:3001`).
Fetches `/api/status-page/:slug` and `/api/status-page/heartbeat/:slug`.
Frontend matches service names to Uptime Kuma monitor names for status badges.

## PWA
- Manifest at `/uploads/manifest.json` — icons point to `/uploads/favicon.png`
- `<link rel="apple-touch-icon" href="/uploads/favicon.png">` for iOS home screen icon
- No service worker — no aggressive caching
- iOS: remove shortcut + re-add from Safari to refresh icon cache
- Android: supports BeforeInstallPromptEvent but not implemented

## OG / Twitter Cards
Meta tags injected in `<head>`:
- `og:image` and `twitter:image` → `/uploads/og-banner.png`
- `og:url` → `https://dashgaard.boogaardmusic.com`

## Deploy pattern
Frontend is baked into the image — any `index.html` change requires a rebuild:
```bash
cp /path/to/index.html /opt/dashgaard/frontend/index.html
cd /opt/dashgaard && docker compose build && docker compose up -d
```
Config and uploaded assets survive rebuilds (Docker volume at `/docker/dashgaard/data`).

## Pending
- Caddy block for `dashgaard.boogaardmusic.com`
- No auth (currently only accessible via Tailscale IP)
