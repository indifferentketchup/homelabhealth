// ──────────────────────────────────────────────────────────────────────────────
// ModelsPanel — bundled model download/status table for the active tier.
// Polls /api/models every 2s while any row is `pulling`; idle otherwise.
// Phase 2.B: Synthetic embed + rerank rows from bundled providers.
// ──────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { cancelPull, listModels, pullModel } from '@/api/models.js'
import { listProviders, testProvider } from '@/api/providers.js'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { RoleCell } from './RoleCell.jsx'

const MAX_SYNTH_ATTEMPTS = 60
const SYNTH_POLL_MS = 5_000

function progressFraction(row) {
  const pulled = Number(row?.pulled_bytes) || 0
  const total = Number(row?.expected_bytes) || 0
  if (total <= 0 || pulled < 0) return null
  return Math.min(1, Math.max(0, pulled / total))
}

function formatBytes(n) {
  const v = Number(n)
  if (!Number.isFinite(v) || v <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let x = v
  let i = 0
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024
    i += 1
  }
  return `${x.toFixed(x >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

function StatusBadge({ status }) {
  let cls = 'bg-muted text-muted-foreground'
  if (status === 'ready') cls = 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
  else if (status === 'pulling') cls = 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
  else if (status === 'failed') cls = 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
  else if (status === 'skipped') cls = 'bg-muted text-muted-foreground'
  else if (status === 'unavailable') cls = 'bg-muted text-muted-foreground'
  else if (status === 'inactive') cls = 'bg-muted text-muted-foreground'
  else if (status === 'loading') cls = 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
  else if (status === 'error') cls = 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
  return (
    <span className={cn('inline-block rounded px-1.5 py-0.5 font-mono text-[11px]', cls)}>
      {status || '—'}
    </span>
  )
}

/**
 * Derive the display state for a synthetic (embed/rerank) row.
 * @param {{ last_verified_status: string|null }} row
 * @param {number} attempts - number of poll attempts so far
 * @returns {{ state: 'ready'|'loading'|'error', msg: string }}
 */
function friendlyError(raw) {
  if (!raw) return null
  if (/ConnectError|Name or service not known|Connection refused/i.test(raw)) {
    return 'Service is starting up — it can take a few minutes to load the model. Try the Test button shortly.'
  }
  if (/timeout|timed out/i.test(raw)) return 'Service is taking a while to respond — the model may still be loading.'
  if (/HTTP 5\d\d/.test(raw)) return 'Service returned a server error. Check container logs for details.'
  return null
}

function syntheticStatus(row, attempts) {
  const lvs = row.last_verified_status
  if (lvs && lvs.startsWith('ok')) return { state: 'ready', msg: '', rawMsg: '' }
  if (lvs && lvs.startsWith('inactive:')) {
    const reason = lvs.slice('inactive: '.length)
    return { state: 'inactive', msg: reason.charAt(0).toUpperCase() + reason.slice(1), rawMsg: '' }
  }
  if (lvs && lvs.startsWith('error:')) {
    const friendly = friendlyError(lvs)
    return { state: 'error', msg: friendly || lvs, rawMsg: friendly ? lvs : '' }
  }
  if ((attempts || 0) >= MAX_SYNTH_ATTEMPTS) {
    return { state: 'error', msg: "Sidecar didn't come up within 5 min. Check container logs.", rawMsg: '' }
  }
  return { state: 'loading', msg: '', rawMsg: '' }
}

const SYNTH_ROLE_META = {
  embed: { model: 'Qwen/Qwen3-Embedding-0.6B', license: 'apache-2.0', license_url: 'https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF' },
  rerank: { model: 'Qwen/Qwen3-Reranker-0.6B', license: 'apache-2.0', license_url: 'https://huggingface.co/ggml-org/Qwen3-Reranker-0.6B-Q8_0-GGUF' },
}

export function ModelsPanel({ currentTier }) {
  const queryClient = useQueryClient()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [actionErr, setActionErr] = useState(null)

  // ── Synthetic row polling state ──────────────────────────────────────────
  const [synthAttempts, setSynthAttempts] = useState({}) // { provider_id: attempt_count }
  const synthAttemptsRef = useRef({})

  useEffect(() => {
    synthAttemptsRef.current = synthAttempts
  }, [synthAttempts])

  const refresh = useCallback(async () => {
    try {
      const data = await listModels()
      const filtered = (data?.items ?? []).filter((r) => r.tier === currentTier)
      setItems(filtered)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load models')
    } finally {
      setLoading(false)
    }
  }, [currentTier])

  useEffect(() => {
    setLoading(true)
    void refresh()
  }, [refresh])

  const anyPulling = useMemo(() => items.some((r) => r.status === 'pulling'), [items])

  useEffect(() => {
    if (!anyPulling) return
    const t = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(t)
  }, [anyPulling, refresh])

  // ── Bundled providers query (for synthetic embed + rerank rows) ──────────
  const { data: providersData } = useQuery({
    queryKey: ['providers'],
    queryFn: () => listProviders(),
    staleTime: 30_000,
  })
  const providers = providersData?.items ?? []

  // Roles that already have a real download row above (chat/embed/rerank/tasks/
  // vision). Since v1.1.4 gave embed/rerank actual download specs, their
  // synthetic provider rows became duplicates — drop those.
  const downloadedRoles = useMemo(() => new Set(items.map((r) => r.role)), [items])

  const syntheticRows = useMemo(
    () =>
      providers
        .filter(
          (p) => p.is_bundled && SYNTH_ROLE_META[p.role] && !downloadedRoles.has(p.role),
        )
        .map((p) => ({
          id: p.id,
          role: p.role,
          model: SYNTH_ROLE_META[p.role].model,
          last_verified_status: p.last_verified_status,
          license: SYNTH_ROLE_META[p.role].license,
          license_url: SYNTH_ROLE_META[p.role].license_url,
        })),
    [providers, downloadedRoles],
  )

  // ── Polling for synthetic rows in "loading" state ────────────────────────
  useEffect(() => {
    const loadingRows = syntheticRows.filter(
      (r) => !r.last_verified_status || r.last_verified_status === '',
    )
    if (loadingRows.length === 0) return

    const interval = window.setInterval(async () => {
      for (const row of loadingRows) {
        const attempts = synthAttemptsRef.current[row.id] || 0
        if (attempts >= MAX_SYNTH_ATTEMPTS) continue
        try {
          await testProvider(row.id)
        } catch {
          /* ignore — provider.last_verified_status is updated server-side */
        }
        setSynthAttempts((cur) => ({ ...cur, [row.id]: (cur[row.id] || 0) + 1 }))
      }
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    }, SYNTH_POLL_MS)

    return () => window.clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syntheticRows, queryClient])
  // Note: synthAttempts intentionally excluded from deps to avoid restarting
  // the interval on every count increment; reads the latest value via
  // setSynthAttempts functional updater instead.

  async function onTestSynthetic(row) {
    // Reset attempt counter so the 60-attempt cap starts fresh.
    setSynthAttempts((cur) => ({ ...cur, [row.id]: 0 }))
    setActionErr(null)
    try {
      await testProvider(row.id)
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : 'Test failed')
    }
  }

  async function onPull(row) {
    setActionErr(null)
    try {
      await pullModel(row.id)
      // Optimistically mark pulling so polling kicks in immediately.
      setItems((cur) => cur.map((r) => (r.id === row.id ? { ...r, status: 'pulling' } : r)))
      await refresh()
    } catch (e) {
      const raw = e instanceof Error ? e.message : 'Pull failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch {
        /* not JSON */
      }
      setActionErr(pretty)
    }
  }

  // Pull all pending rows in sequence. The puller serializes via _PULL_LOCK
  // server-side anyway, so firing them one-by-one with awaits keeps the UI
  // honest about which row is "in flight" right now.
  const pendingRows = useMemo(
    () => items.filter((r) => r.status === 'pending' || r.status === 'failed'),
    [items],
  )
  const [pullingAll, setPullingAll] = useState(false)
  async function onPullAll() {
    if (pullingAll || pendingRows.length === 0) return
    setPullingAll(true)
    setActionErr(null)
    try {
      for (const row of pendingRows) {
        try {
          await pullModel(row.id)
          setItems((cur) => cur.map((r) => (r.id === row.id ? { ...r, status: 'pulling' } : r)))
        } catch (e) {
          const raw = e instanceof Error ? e.message : 'Pull failed'
          let pretty = raw
          try {
            const parsed = JSON.parse(raw)
            if (parsed?.detail) pretty = String(parsed.detail)
          } catch { /* not JSON */ }
          setActionErr(`${row.role}: ${pretty}`)
          // Continue to next row — one failure shouldn't block the rest.
        }
      }
      await refresh()
    } finally {
      setPullingAll(false)
    }
  }

  async function onCancel(row) {
    setActionErr(null)
    try {
      await cancelPull(row.id)
      await refresh()
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : 'Cancel failed')
    }
  }

  return (
    <div className="space-y-2" data-testid="system-models-panel">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">Models for this tier</h3>
        <span className="text-xs text-muted-foreground">tier: <span className="font-mono">{currentTier || '—'}</span></span>
      </div>
      <p className="text-xs text-muted-foreground">
        Bundled-AI artifacts the operator downloads to the local cache. Polls every 2s while a pull
        is active. Gated rows (MedGemma) need an <span className="font-mono">HF_TOKEN</span> and a
        license click at the linked HF page.
      </p>
      <p className="text-xs text-muted-foreground">
        Embed and rerank weights are downloaded automatically by their
        sidecars on first boot. They appear as{' '}
        <span className="font-mono">loading</span> until the sidecar reports healthy, then{' '}
        <span className="font-mono">ready</span>. No Pull button — the sidecar manages itself.
      </p>

      {actionErr ? <p className="text-sm text-destructive">{actionErr}</p> : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {/* First-install / post-tier-change prompt. Surfaces whenever pending or
          failed rows exist; one click queues them all (serialized server-side
          via _PULL_LOCK in model_puller). */}
      {!loading && pendingRows.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/40 bg-primary/5 p-3">
          <div className="text-sm">
            <span className="font-medium text-foreground">
              {pendingRows.length} model{pendingRows.length === 1 ? '' : 's'} ready to download
            </span>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Sequential downloads — watch the per-row progress bar below.
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            onClick={() => void onPullAll()}
            disabled={pullingAll || anyPulling}
            data-testid="system-models-pull-all"
          >
            {pullingAll ? 'Queuing…' : 'Pull all'}
          </Button>
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading models…</p>
      ) : items.length === 0 && syntheticRows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No bundled artifacts for this tier (or you picked <span className="font-mono">external</span>).
        </p>
      ) : (
        <TooltipProvider>
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full table-auto text-sm">
            <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="px-3 py-2 font-medium">Model</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Progress</th>
                <th className="px-3 py-2 font-medium">License</th>
                <th className="px-3 py-2 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {/* Puller-driven chat rows */}
              {items.map((row) => {
                const frac = progressFraction(row)
                return (
                  <tr key={row.id} className="border-t border-border align-top">
                    <td className="px-3 py-2"><RoleCell role={row.role} /></td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground" title={row.model_id}>
                      <div>{row.repo}</div>
                      <div className="text-[11px]">{row.filename}{row.quant ? ` · ${row.quant}` : ''}</div>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={row.status} />
                      {row.error_message ? (
                        <div className="mt-1 text-xs text-destructive" data-testid={`system-model-error-${row.role}`}>
                          {row.error_message}
                          {/* Only surface the license link when the puller reported a
                              401-style license-acceptance error; otherwise the link is
                              misleading (a 404 means the file is missing, not gated). */}
                          {row.license_url && row.error_message.startsWith('License acceptance') ? (
                            <>
                              {' '}
                              <a
                                href={row.license_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="underline underline-offset-2 hover:text-foreground"
                              >
                                Visit and accept here.
                              </a>
                            </>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.status === 'pulling' || row.status === 'ready' ? (
                        <div className="flex flex-col gap-1">
                          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full bg-primary transition-all"
                              style={{ width: `${Math.round(((frac ?? 0) * 100))}%` }}
                              data-testid={`system-model-progress-${row.role}`}
                            />
                          </div>
                          <span className="font-mono text-[11px] text-muted-foreground">
                            {formatBytes(row.pulled_bytes)} / {formatBytes(row.expected_bytes)}
                            {frac != null ? ` (${Math.round(frac * 100)}%)` : ''}
                          </span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.license ? (
                        <a
                          href={row.license_url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline underline-offset-2 hover:text-foreground"
                          title={row.license_url || ''}
                        >
                          {row.license}
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {row.status === 'pulling' ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void onCancel(row)}
                          data-testid={`system-model-cancel-${row.role}`}
                        >
                          Cancel
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void onPull(row)}
                          data-testid={`system-model-pull-${row.role}`}
                        >
                          {row.status === 'ready' ? 'Re-pull' : 'Pull'}
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}

              {/* Synthetic embed + rerank rows (Phase 2.B) */}
              {syntheticRows.map((row) => {
                const { state, msg, rawMsg } = syntheticStatus(row, synthAttempts[row.id])
                return (
                  <tr
                    key={row.id}
                    className="border-t border-border align-top"
                    data-testid={`system-synth-row-${row.role}`}
                  >
                    <td className="px-3 py-2"><RoleCell role={row.role} /></td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                      {row.model}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={state} />
                      {state === 'inactive' && msg ? (
                        <div className="mt-1 text-xs text-muted-foreground">{msg}</div>
                      ) : state === 'error' && msg ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div
                              className="mt-1 text-xs text-destructive cursor-default"
                              data-testid={`system-synth-error-${row.role}`}
                            >
                              {msg}
                            </div>
                          </TooltipTrigger>
                          {rawMsg ? (
                            <TooltipContent side="bottom" className="max-w-sm">
                              <p className="font-mono text-[11px] break-all">{rawMsg}</p>
                            </TooltipContent>
                          ) : null}
                        </Tooltip>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {state === 'loading' ? (
                        <span
                          className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent text-sky-600"
                          aria-label="loading"
                        />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.license ? (
                        <a
                          href={row.license_url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline underline-offset-2 hover:text-foreground"
                          title={row.license_url || ''}
                        >
                          {row.license}
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex flex-col items-end gap-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void onTestSynthetic(row)}
                          data-testid={`system-synth-test-${row.role}`}
                        >
                          Test
                        </Button>
                        <span className="text-[11px] text-muted-foreground">sidecar-managed</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        </TooltipProvider>
      )}
    </div>
  )
}
