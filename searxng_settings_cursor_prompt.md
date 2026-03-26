# Cursor — boolab: Integrate SearXNG Settings

## Task
Wire SearXNG configuration into boolab's branding/settings system so all search engine config lives on the Settings page alongside AI settings.

---

## Phase 1: Backend Schema + API

### 1a. Database Schema
Add to `backend/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS searxng_config (
  id SERIAL PRIMARY KEY,
  mode TEXT NOT NULL UNIQUE,
  safe_search INTEGER DEFAULT 0,  -- 0: None, 1: Moderate, 2: Strict
  image_proxy BOOLEAN DEFAULT false,
  enabled_engines TEXT DEFAULT 'google,duckduckgo,bing,wikipedia',  -- comma-separated
  autocomplete TEXT DEFAULT '',  -- engine name or empty
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Seed defaults for booops and 808notes
INSERT INTO searxng_config (mode, safe_search, image_proxy, enabled_engines, autocomplete)
VALUES
  ('booops', 0, false, 'google,duckduckgo,bing,wikipedia,github', ''),
  ('808notes', 0, false, 'google,duckduckgo,bing,wikipedia', '')
ON CONFLICT (mode) DO NOTHING;
```

### 1b. New Endpoint: `backend/routers/searxng.py`

```python
from fastapi import APIRouter, HTTPException
from db import get_pool
import yaml
import os

router = APIRouter(prefix="/api/searxng", tags=["search"])

SEARXNG_CONFIG_PATH = "/etc/searxng/settings.yml"  # or wherever it's mounted

@router.get("/{mode}")
async def get_searxng_config(mode: str):
    """Get SearXNG config for a mode."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT safe_search, image_proxy, enabled_engines, autocomplete FROM searxng_config WHERE mode = $1",
            mode
        )
        if not row:
            raise HTTPException(status_code=404, detail="Mode not found")
        return {
            "mode": mode,
            "safe_search": row["safe_search"],
            "image_proxy": row["image_proxy"],
            "enabled_engines": row["enabled_engines"].split(","),
            "autocomplete": row["autocomplete"]
        }

@router.patch("/{mode}")
async def update_searxng_config(mode: str, config: dict):
    """Update SearXNG config for a mode.
    
    Body:
    {
      "safe_search": 0,
      "image_proxy": false,
      "enabled_engines": ["google", "duckduckgo", "bing"],
      "autocomplete": "google"  # or ""
    }
    """
    # Validate
    if config.get("safe_search") not in [0, 1, 2]:
        raise HTTPException(status_code=400, detail="safe_search must be 0, 1, or 2")
    
    # Update DB
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE searxng_config 
               SET safe_search = $1, image_proxy = $2, enabled_engines = $3, autocomplete = $4, updated_at = NOW()
               WHERE mode = $5""",
            config.get("safe_search", 0),
            config.get("image_proxy", False),
            ",".join(config.get("enabled_engines", [])),
            config.get("autocomplete", ""),
            mode
        )
    
    # Write to SearXNG settings.yml
    await _write_searxng_settings(mode, config)
    
    # Reload SearXNG container (if needed)
    # os.system("docker compose -f /opt/boolab/ restart boolab_ui")  # or skip if live reload works
    
    return {"status": "updated", "mode": mode}

async def _write_searxng_settings(mode: str, config: dict):
    """Write enabled_engines and safe_search to SearXNG settings.yml."""
    if not os.path.exists(SEARXNG_CONFIG_PATH):
        raise HTTPException(status_code=500, detail="SearXNG config not found")
    
    with open(SEARXNG_CONFIG_PATH, "r") as f:
        settings = yaml.safe_load(f)
    
    # Update search settings
    settings["search"]["safe_search"] = config.get("safe_search", 0)
    settings["server"]["image_proxy"] = config.get("image_proxy", False)
    settings["search"]["autocomplete"] = config.get("autocomplete", "")
    
    # Disable all engines, then enable selected ones
    enabled_names = set(config.get("enabled_engines", []))
    for engine in settings.get("engines", []):
        if isinstance(engine, dict):
            name = list(engine.keys())[0]
            if name in enabled_names:
                engine[name]["disabled"] = False
            else:
                engine[name]["disabled"] = True
    
    # Write back
    with open(SEARXNG_CONFIG_PATH, "w") as f:
        yaml.dump(settings, f)
```

### 1c. Register Router in `backend/main.py`

```python
from routers import searxng

app.include_router(searxng.router)
```

---

## Phase 2: Frontend Settings Tab

### 2a. Add to `frontend/src/pages/booops/SettingsPage.jsx`

In the tab list, add:
```jsx
<button
  className={`tab ${activeTab === "search" ? "active" : ""}`}
  onClick={() => setActiveTab("search")}
>
  Search
</button>
```

In the tab content, add:
```jsx
{activeTab === "search" && (
  <SearchSettingsTab />
)}
```

### 2b. New Component: `frontend/src/components/settings/SearchSettingsTab.jsx`

```jsx
import { useEffect, useState } from "react";
import { fetchSearchConfig, updateSearchConfig } from "../../api/search";
import Button from "../ui/button";

const AVAILABLE_ENGINES = [
  "google",
  "duckduckgo",
  "bing",
  "wikipedia",
  "github",
  "arxiv",
  "pubmed",
];

export default function SearchSettingsTab() {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const data = await fetchSearchConfig("booops");
        setConfig(data);
      } catch (err) {
        console.error("Failed to load search config:", err);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  const handleEngineToggle = (engine) => {
    setConfig({
      ...config,
      enabled_engines: config.enabled_engines.includes(engine)
        ? config.enabled_engines.filter((e) => e !== engine)
        : [...config.enabled_engines, engine],
    });
  };

  const handleSave = async () => {
    try {
      await updateSearchConfig("booops", config);
      // Toast success
    } catch (err) {
      console.error("Failed to save search config:", err);
      // Toast error
    }
  };

  if (loading) return <div>Loading...</div>;
  if (!config) return <div>Failed to load config</div>;

  return (
    <div className="settings-tab">
      <h3>Search Settings</h3>

      <div className="setting-group">
        <label>Safe Search</label>
        <select
          value={config.safe_search}
          onChange={(e) =>
            setConfig({ ...config, safe_search: parseInt(e.target.value) })
          }
        >
          <option value={0}>None</option>
          <option value={1}>Moderate</option>
          <option value={2}>Strict</option>
        </select>
      </div>

      <div className="setting-group">
        <label>
          <input
            type="checkbox"
            checked={config.image_proxy}
            onChange={(e) =>
              setConfig({ ...config, image_proxy: e.target.checked })
            }
          />
          Proxy Images
        </label>
      </div>

      <div className="setting-group">
        <label>Enabled Engines</label>
        <div className="engines-grid">
          {AVAILABLE_ENGINES.map((engine) => (
            <label key={engine}>
              <input
                type="checkbox"
                checked={config.enabled_engines.includes(engine)}
                onChange={() => handleEngineToggle(engine)}
              />
              {engine.charAt(0).toUpperCase() + engine.slice(1)}
            </label>
          ))}
        </div>
      </div>

      <div className="setting-group">
        <label>Autocomplete Engine</label>
        <select
          value={config.autocomplete}
          onChange={(e) => setConfig({ ...config, autocomplete: e.target.value })}
        >
          <option value="">None</option>
          <option value="google">Google</option>
          <option value="duckduckgo">DuckDuckGo</option>
        </select>
      </div>

      <Button onClick={handleSave}>Save Search Settings</Button>
    </div>
  );
}
```

### 2c. API Wrapper: `frontend/src/api/search.js`

```js
export async function fetchSearchConfig(mode) {
  const res = await fetch(`/api/searxng/${mode}`);
  if (!res.ok) throw new Error("Failed to fetch search config");
  return res.json();
}

export async function updateSearchConfig(mode, config) {
  const res = await fetch(`/api/searxng/${mode}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error("Failed to update search config");
  return res.json();
}
```

---

## Constraints

- **DB:** UUIDs or SERIAL — use SERIAL for `searxng_config.id`
- **YAML write:** Use PyYAML's `safe_load/safe_dump`; preserve structure when writing back
- **Engine list:** Keep it simple — only toggle `disabled` flag, don't restructure
- **Container reload:** Skip if SearXNG supports live reload; otherwise add `docker compose ... restart` call
- **No hardcoded hex:** Use CSS vars in SearchSettingsTab
- **Mode:** Hardcode `"booops"` for now; extend to `"808notes"` later if needed

---

## Test Workflow

1. Rebuild: `docker compose build boolab_api && docker compose up -d`
2. Navigate to Settings → Search tab
3. Toggle engines, safe search level
4. Click Save
5. Check SearXNG `/etc/searxng/settings.yml` — engines should be marked `disabled: true/false`
6. Verify in boolab chat: web search should only use enabled engines

---

## Done When

- Search Settings tab renders with all controls
- Save writes to DB + SearXNG config file
- Web search respects `safe_search` + `enabled_engines` flags
- No console errors
