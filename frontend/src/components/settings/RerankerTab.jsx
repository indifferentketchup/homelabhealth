import { useEffect, useState } from 'react'

import { listProviders, listProviderModels } from '@/api/providers.js'
import { getRerankerSettings, putRerankerSettings } from '@/api/settings.js'
import { getSystemProfile } from '@/api/system.js'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

const SELECT_CLASS =
  'h-9 w-full max-w-md rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2 disabled:opacity-50'

export default function RerankerTab() {
  const [loading, setLoading] = useState(true)
  const [tier, setTier] = useState(null)
  const [providers, setProviders] = useState([])
  const [providerId, setProviderId] = useState('')
  const [models, setModels] = useState([])
  const [modelsState, setModelsState] = useState({ loading: false, error: null })
  const [model, setModel] = useState('')
  const [saveErr, setSaveErr] = useState(null)
  const [saveMsg, setSaveMsg] = useState(null)
  const [busy, setBusy] = useState(false)
  const [confirmingClear, setConfirmingClear] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [provList, current, profile] = await Promise.all([
          listProviders(),
          getRerankerSettings(),
          getSystemProfile(),
        ])
        if (cancelled) return
        setTier(profile?.tier ?? null)
        const enabled = (provList?.items ?? []).filter((p) => p.enabled)
        setProviders(enabled)
        const savedPid = current?.provider_id ?? ''
        const savedModel = current?.model ?? ''
        if (savedPid && enabled.some((p) => p.id === savedPid)) {
          setProviderId(savedPid)
          setModel(savedModel)
        }
      } catch (e) {
        if (!cancelled) {
          setSaveErr(e instanceof Error ? e.message : 'Failed to load reranker settings')
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
      await putRerankerSettings({ provider_id: providerId, model })
      setSaveMsg('Reranker model saved.')
    } catch (e) {
      const raw = e instanceof Error ? e.message : 'Save failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch {
        /* not JSON */
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
      await putRerankerSettings({ provider_id: null, model: null })
      setProviderId('')
      setModel('')
      setModels([])
      setSaveMsg('Reranker cleared. Using flashrank fallback.')
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
        <p className="text-sm text-muted-foreground">Loading reranker settings…</p>
      </section>
    )
  }

  if (tier && tier !== 'external') {
    return (
      <section className="mx-auto w-full max-w-2xl space-y-4">
        <div>
          <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">
            Reranker model
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Optional. Improves retrieval ordering. Disable to fall back to flashrank CPU.
          </p>
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm">
            <span className="font-mono text-foreground">BAAI/bge-reranker-v2-m3</span>
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Bundled by HomeLab Health AI. Change hardware tier in{' '}
            <span className="text-foreground">Settings → System</span> to swap reranker behavior.
          </p>
        </div>
      </section>
    )
  }

  return (
    <section className="mx-auto w-full max-w-2xl space-y-5">
      <div>
        <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Reranker model</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Optional. Improves RAG retrieval quality by re-ranking the top-K vector hits. Leave unset to use the built-in{' '}
          <span className="font-mono text-xs text-foreground">flashrank</span> CPU fallback. No probe — the runtime
          soft-fails to flashrank if the configured reranker is unreachable or returns a bad response.
        </p>
      </div>

      {saveErr ? (
        <p data-testid="reranker-save-error" className="text-sm text-destructive">
          {saveErr}
        </p>
      ) : null}
      {saveMsg ? <p className="text-sm text-foreground">{saveMsg}</p> : null}

      <div className="grid gap-1.5">
        <Label htmlFor="reranker-provider">Provider</Label>
        <select
          id="reranker-provider"
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
        <Label htmlFor="reranker-model">Model</Label>
        <select
          id="reranker-model"
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
            Use flashrank fallback
          </Button>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Revert to built-in flashrank CPU reranker?</span>
            <Button type="button" size="sm" variant="destructive" onClick={() => void onClear()} disabled={busy}>
              {busy ? 'Clearing…' : 'Yes, use flashrank'}
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
