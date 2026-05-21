import { useEffect, useState } from 'react'

import { listProviders, listProviderModels } from '@/api/providers.js'
import { getEmbeddingSettings, putEmbeddingSettings } from '@/api/settings.js'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

const SELECT_CLASS =
  'h-9 w-full max-w-md rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2 disabled:opacity-50'

export default function EmbeddingTab() {
  const [loading, setLoading] = useState(true)
  const [providers, setProviders] = useState([])
  const [providerId, setProviderId] = useState('')
  const [models, setModels] = useState([])
  const [modelsState, setModelsState] = useState({ loading: false, error: null })
  const [model, setModel] = useState('')
  const [dimension, setDimension] = useState(1024)
  const [saveErr, setSaveErr] = useState(null)
  const [saveMsg, setSaveMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmingClear, setConfirmingClear] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [provList, current] = await Promise.all([
          listProviders(),
          getEmbeddingSettings(),
        ])
        if (cancelled) return
        const enabled = (provList?.items ?? []).filter((p) => p.enabled)
        setProviders(enabled)
        setDimension(current?.dimension ?? 1024)
        const savedPid = current?.provider_id ?? ''
        const savedModel = current?.model ?? ''
        if (savedPid && enabled.some((p) => p.id === savedPid)) {
          setProviderId(savedPid)
          setModel(savedModel)
        }
      } catch (e) {
        if (!cancelled) {
          setSaveErr(e instanceof Error ? e.message : 'Failed to load embedding settings')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // Fetch the chosen provider's /v1/models whenever provider_id changes.
  useEffect(() => {
    if (!providerId) {
      setModels([])
      setModelsState({ loading: false, error: null })
      return
    }
    let cancelled = false
    setModelsState({ loading: true, error: null })
    ;(async () => {
      try {
        const data = await listProviderModels(providerId)
        if (cancelled) return
        const ids = (data?.data ?? [])
          .map((m) => (typeof m?.id === 'string' ? m.id : null))
          .filter((s) => !!s)
        setModels(ids)
        setModelsState({ loading: false, error: null })
        // If the previously-saved model is no longer in the list, clear it
        // so the dropdown doesn't show a phantom selection.
        if (model && !ids.includes(model)) setModel('')
      } catch (e) {
        if (!cancelled) {
          setModels([])
          setModelsState({
            loading: false,
            error: e instanceof Error ? e.message : 'Failed to load models',
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [providerId])  // eslint-disable-line react-hooks/exhaustive-deps

  async function onSave() {
    if (!providerId || !model) {
      setSaveErr('Pick both a provider and a model first.')
      return
    }
    setSaveErr(null)
    setSaveMsg(null)
    setBusy(true)
    try {
      await putEmbeddingSettings({ provider_id: providerId, model })
      setSaveMsg('Embedding model saved.')
    } catch (e) {
      // apiFetch throws Error with the response body as message. The backend
      // returns FastAPI {detail: "..."} JSON; if it's a dim mismatch, the
      // verbatim spec string is inside that detail. Surface as-is.
      const raw = e instanceof Error ? e.message : 'Save failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch {
        /* not JSON, keep raw */
      }
      setSaveErr(pretty)
    } finally {
      setBusy(false)
    }
  }

  async function onClear() {
    setSaveErr(null)
    setSaveMsg(null)
    setBusy(true)
    try {
      await putEmbeddingSettings({ provider_id: null, model: null })
      setProviderId('')
      setModel('')
      setModels([])
      setSaveMsg('Embedding model cleared. RAG ingest and retrieval will fail until reconfigured.')
    } catch (e) {
      setSaveErr(e instanceof Error ? e.message : 'Clear failed')
    } finally {
      setBusy(false)
      setConfirmingClear(false)
    }
  }

  useEffect(() => {
    if (!saveMsg) return
    const t = window.setTimeout(() => setSaveMsg(null), 5000)
    return () => window.clearTimeout(t)
  }, [saveMsg])

  if (loading) {
    return (
      <section className="mx-auto w-full max-w-2xl">
        <p className="text-sm text-muted-foreground">Loading embedding settings…</p>
      </section>
    )
  }

  return (
    <section className="mx-auto w-full max-w-2xl space-y-5">
      <div>
        <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Embedding model</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          One global selection. Used by every ingest, every retrieval, and every memory entry. The provider must serve a
          model that returns <span className="font-mono text-xs text-foreground">{dimension}</span>-dimensional vectors;
          probing happens at save time.
        </p>
      </div>

      {saveErr ? (
        <p data-testid="embedding-save-error" className="text-sm text-destructive">
          {saveErr}
        </p>
      ) : null}
      {saveMsg ? <p className="text-sm text-foreground">{saveMsg}</p> : null}

      <div className="grid gap-1.5">
        <Label htmlFor="embedding-provider">Provider</Label>
        <select
          id="embedding-provider"
          className={SELECT_CLASS}
          value={providerId}
          onChange={(e) => {
            setProviderId(e.target.value)
            setModel('')
          }}
          disabled={busy}
        >
          <option value="">— pick an enabled provider —</option>
          {providers.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {providers.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            No enabled providers. Add one in Settings → Providers first.
          </p>
        ) : null}
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor="embedding-model">Model</Label>
        <select
          id="embedding-model"
          className={SELECT_CLASS}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          disabled={busy || !providerId || modelsState.loading}
        >
          <option value="">
            {!providerId
              ? '— pick a provider first —'
              : modelsState.loading
                ? 'Loading models…'
                : modelsState.error
                  ? '— failed to load models —'
                  : models.length === 0
                    ? '— no models reported by provider —'
                    : '— pick a model —'}
          </option>
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        {modelsState.error ? (
          <p className="text-xs text-destructive">{modelsState.error}</p>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={() => void onSave()} disabled={busy || !providerId || !model}>
          {busy ? 'Saving…' : 'Save'}
        </Button>

        {!confirmingClear ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setConfirmingClear(true)}
            disabled={busy}
          >
            Clear (disable embeddings)
          </Button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-destructive">Sure? RAG ingest + retrieval will fail until reconfigured.</span>
            <Button type="button" size="sm" variant="destructive" onClick={() => void onClear()} disabled={busy}>
              {busy ? 'Clearing…' : 'Yes, clear'}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirmingClear(false)} disabled={busy}>
              Cancel
            </Button>
          </div>
        )}
      </div>
    </section>
  )
}
