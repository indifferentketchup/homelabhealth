import { useEffect, useState } from 'react'

import { fetchSearxngConfig, patchSearxngConfig } from '@/api/searxngConfig.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** [searx engine id, label] — ids must match SearXNG engine `name` (lowercase). */
const AVAILABLE_ENGINES = [
  ['brave', 'Brave'],
  ['mojeek', 'Mojeek'],
  ['startpage', 'Startpage'],
  ['qwant', 'Qwant'],
  ['presearch', 'Presearch'],
  ['marginalia', 'Marginalia'],
  ['wikipedia', 'Wikipedia'],
  ['github', 'GitHub'],
  ['arxiv', 'arXiv'],
  ['pubmed', 'PubMed'],
]

/** Values accepted by SearXNG search.autocomplete (subset; empty = instance default) */
const AUTOCOMPLETE_OPTIONS = [
  ['', 'None'],
  ['google', 'Google'],
  ['duckduckgo', 'DuckDuckGo'],
  ['wikipedia', 'Wikipedia'],
  ['startpage', 'Startpage'],
  ['qwant', 'Qwant'],
  ['swisscows', 'Swisscows'],
  ['dbpedia', 'DBpedia'],
]

const selectClass =
  'h-9 w-full max-w-md rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2'

export default function SearchSettingsTab() {
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saveMsg, setSaveMsg] = useState(null)
  const [saveErr, setSaveErr] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setSaveMsg(null)
    setSaveErr(null)
    ;(async () => {
      try {
        const data = await fetchSearxngConfig()
        if (!cancelled) setConfig(data)
      } catch (e) {
        if (!cancelled) {
          setConfig(null)
          setSaveErr(e instanceof Error ? e.message : 'Failed to load search settings')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const handleEngineToggle = (engine) => {
    if (!config) return
    const has = config.enabled_engines.includes(engine)
    setConfig({
      ...config,
      enabled_engines: has
        ? config.enabled_engines.filter((e) => e !== engine)
        : [...config.enabled_engines, engine],
    })
  }

  async function handleSave() {
    if (!config) return
    setSaveMsg(null)
    setSaveErr(null)
    try {
      await patchSearxngConfig({
        safe_search: config.safe_search,
        image_proxy: config.image_proxy,
        enabled_engines: config.enabled_engines,
        autocomplete: config.autocomplete || '',
      })
      setSaveMsg('Search settings saved.')
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : 'Save failed')
    }
  }

  useEffect(() => {
    if (!saveMsg) return
    const t = window.setTimeout(() => setSaveMsg(null), 4000)
    return () => window.clearTimeout(t)
  }, [saveMsg])

  if (loading) {
    return (
      <section className="mx-auto w-full max-w-2xl">
        <p className="text-sm text-muted-foreground">Loading search settings…</p>
      </section>
    )
  }

  if (!config) {
    return (
      <section className="mx-auto w-full max-w-2xl space-y-2">
        <p className="text-sm text-destructive">{saveErr || 'Could not load search settings.'}</p>
      </section>
    )
  }

  return (
    <section className="mx-auto w-full max-w-2xl space-y-5">
      <div>
        <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Search (SearXNG)</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Applies to web search. The app sends safe search, engines, and related flags on each request. Optionally set{' '}
          <span className="font-mono text-xs text-foreground">SEARXNG_SETTINGS_YML</span> on the API to mirror toggles into
          SearXNG&apos;s config file.
        </p>
      </div>

      {saveErr ? <p className="text-sm text-destructive">{saveErr}</p> : null}
      {saveMsg ? <p className="text-sm text-foreground">{saveMsg}</p> : null}

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Safe search</span>
        <select
          className={selectClass}
          value={config.safe_search}
          onChange={(e) =>
            setConfig({ ...config, safe_search: parseInt(e.target.value, 10) })
          }
        >
          <option value={0}>None</option>
          <option value={1}>Moderate</option>
          <option value={2}>Strict</option>
        </select>
      </label>

      <label className="flex cursor-pointer items-center gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          className={cn(
            'size-4 shrink-0 rounded border border-border bg-background',
            'text-primary focus-visible:ring-2 focus-visible:ring-ring',
          )}
          checked={config.image_proxy}
          onChange={(e) => setConfig({ ...config, image_proxy: e.target.checked })}
        />
        <span>Proxy images via SearXNG</span>
      </label>

      <div className="space-y-2 text-sm">
        <span className="text-muted-foreground">Enabled engines</span>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {AVAILABLE_ENGINES.map(([engine, label]) => (
            <label
              key={engine}
              className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-card/30 px-3 py-2 text-foreground"
            >
              <input
                type="checkbox"
                className="size-4 shrink-0 rounded border border-border bg-background text-primary focus-visible:ring-2 focus-visible:ring-ring"
                checked={config.enabled_engines.includes(engine)}
                onChange={() => handleEngineToggle(engine)}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-muted-foreground">Autocomplete (SearXNG)</span>
        <select
          className={selectClass}
          value={config.autocomplete || ''}
          onChange={(e) => setConfig({ ...config, autocomplete: e.target.value })}
        >
          {AUTOCOMPLETE_OPTIONS.map(([value, label]) => (
            <option key={value || 'none'} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>

      <Button type="button" size="sm" onClick={() => void handleSave()}>
        Save search settings
      </Button>
    </section>
  )
}
