import { useEffect, useMemo, useState } from 'react'

import { ChevronDown, Lock } from 'lucide-react'

import {
  createProvider,
  deleteProvider,
  listProviders,
  patchProvider,
  testProvider,
} from '@/api/providers.js'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

const KEY_FIELD_PLACEHOLDER_KEPT = '•••••••• (leave blank to keep)'

function relativeTime(iso) {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return '—'
  const diff = Math.max(0, Date.now() - t)
  const s = Math.floor(diff / 1000)
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

function statusBadgeClass(status) {
  if (status === 'ok') return 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
  if (status && status.startsWith('error:')) return 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
  return 'bg-muted text-muted-foreground'
}

/** Modal lives inside the page so its state is isolated. */
function ProviderFormDialog({ open, onOpenChange, initial, onSaved }) {
  const isEdit = !!initial
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [sortOrder, setSortOrder] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    if (!open) return
    setErr(null)
    setSubmitting(false)
    setName(initial?.name ?? '')
    setBaseUrl(initial?.base_url ?? '')
    setApiKey('')
    setEnabled(initial?.enabled ?? true)
    setSortOrder(initial?.sort_order ?? 0)
  }, [open, initial])

  async function onSubmit(event) {
    event.preventDefault()
    setErr(null)
    setSubmitting(true)
    try {
      if (isEdit) {
        // Only include api_key in the PATCH if the user typed something.
        // Empty field on edit = preserve current key (omit field entirely).
        const body = {
          name,
          base_url: baseUrl,
          enabled,
          sort_order: Number(sortOrder) || 0,
        }
        if (apiKey.length > 0) body.api_key = apiKey
        await patchProvider(initial.id, body)
      } else {
        // On Add, empty = no auth (api_key: null). Non-empty = the literal string.
        await createProvider({
          name,
          base_url: baseUrl,
          api_key: apiKey.length > 0 ? apiKey : null,
          enabled,
          sort_order: Number(sortOrder) || 0,
        })
      }
      onSaved()
      onOpenChange(false)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSubmitting(false)
    }
  }

  async function onClearKey() {
    if (!isEdit) return
    setErr(null)
    setSubmitting(true)
    try {
      await patchProvider(initial.id, { api_key: null })
      onSaved()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Clear failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? 'Edit provider' : 'Add provider'}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? 'API key field is blank by design. Leave it empty to keep the current key.'
              : 'OpenAI-compatible base URL. API key is optional for local backends.'}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="grid gap-3">
          <div className="grid gap-1.5">
            <Label htmlFor="provider-name">Name</Label>
            <Input
              id="provider-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus={!isEdit}
              placeholder="e.g. local-llamacpp"
            />
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="provider-base-url">Base URL</Label>
            <Input
              id="provider-base-url"
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              required
              placeholder="http://localhost:8080"
            />
          </div>

          <div className="grid gap-1.5">
            <div className="flex items-baseline justify-between">
              <Label htmlFor="provider-api-key">API key</Label>
              {isEdit && initial?.api_key === '***' ? (
                <span className="text-xs text-muted-foreground">
                  currently set
                  <button
                    type="button"
                    className="ml-2 text-xs underline underline-offset-2 hover:text-foreground disabled:opacity-50"
                    onClick={() => void onClearKey()}
                    disabled={submitting}
                  >
                    Clear key
                  </button>
                </span>
              ) : null}
            </div>
            <Input
              id="provider-api-key"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={
                isEdit && initial?.api_key === '***'
                  ? KEY_FIELD_PLACEHOLDER_KEPT
                  : 'optional — leave blank for no auth'
              }
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4 rounded border border-border bg-background text-primary focus-visible:ring-2 focus-visible:ring-ring"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              Enabled
            </label>
            <div className="grid gap-1.5">
              <Label htmlFor="provider-sort-order" className="text-xs text-muted-foreground">
                Sort order
              </Label>
              <Input
                id="provider-sort-order"
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                step={1}
              />
            </div>
          </div>

          {err ? <p className="text-sm text-destructive">{err}</p> : null}

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Saving…' : isEdit ? 'Save' : 'Add provider'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteConfirmDialog({ open, onOpenChange, provider, refs, onConfirm, busy }) {
  if (!provider) return null
  const counts = refs ?? null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {counts ? `${provider.name} is in use` : `Delete ${provider.name}?`}
          </DialogTitle>
          <DialogDescription>
            {counts ? (
              <>
                The following references will be cleared if you force-delete:
                <ul className="mt-2 list-disc pl-5 text-foreground">
                  <li>
                    {counts.workspaces} workspace{counts.workspaces === 1 ? '' : 's'} bound to this provider (provider_id + model nulled)
                  </li>
                  {counts.embedding ? <li>Embedding model setting (will be cleared — ingest stops until you reconfigure)</li> : null}
                  {counts.reranker ? <li>Reranker model setting (will be cleared — flashrank fallback)</li> : null}
                </ul>
              </>
            ) : (
              'This cannot be undone.'
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => onConfirm({ force: !!counts })}
            disabled={busy}
          >
            {busy ? 'Deleting…' : counts ? 'Force delete (clears references)' : 'Delete'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const BUNDLE_GROUP_DISPLAY_NAMES = {
  'homelab-health-ai': 'HomeLab Health AI',
}

function BundledGroupCard({ groupKey, rows, testResults, onTest }) {
  const [open, setOpen] = useState(false)
  const displayName = BUNDLE_GROUP_DISPLAY_NAMES[groupKey] ?? groupKey

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-2">
          <Lock className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium text-foreground">{displayName}</span>
          <span className="text-xs text-muted-foreground">
            ({rows.length} bundled sidecar{rows.length === 1 ? '' : 's'})
          </span>
        </div>
        <ChevronDown
          className={cn('h-4 w-4 text-muted-foreground transition-transform', open ? 'rotate-180' : '')}
        />
      </button>
      {open ? (
        <div className="space-y-2 border-t border-border p-3">
          {rows.map((r) => {
            const tr = testResults[r.id]
            return (
              <div key={r.id} className="rounded-md border border-border bg-background p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-foreground">{r.name}</span>
                      {r.role ? (
                        <span className="shrink-0 rounded-full bg-muted px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                          {r.role}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{r.base_url}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => void onTest(r)}
                      disabled={tr?.running}
                    >
                      {tr?.running ? 'Testing…' : 'Test'}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled
                      title="Bundled by the homelabhealth stack — not editable"
                    >
                      Edit
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled
                      title="Bundled by the homelabhealth stack — not deletable"
                    >
                      Delete
                    </Button>
                  </div>
                </div>
                {tr && !tr.running ? (
                  <div
                    className={cn(
                      'mt-2 text-xs',
                      tr.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400',
                    )}
                  >
                    {tr.ok ? `ok — ${(tr.models ?? []).length} models` : tr.status}
                    {tr.ok && tr.models?.length ? (
                      <details className="mt-0.5">
                        <summary className="cursor-pointer text-muted-foreground hover:text-foreground">show ids</summary>
                        <ul className="mt-1 list-disc pl-5 font-mono text-[11px] text-muted-foreground">
                          {tr.models.map((m) => (
                            <li key={m}>{m}</li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </div>
                ) : null}
                {!tr && r.last_verified_status ? (
                  <p className="mt-2 text-xs text-muted-foreground">
                    Last verified: {r.last_verified_status}
                    {r.last_verified_at ? ` · ${relativeTime(r.last_verified_at)}` : ''}
                  </p>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

export default function ProvidersTab() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null) // null = closed; { add: true } or { add: false, provider }
  const [deleting, setDeleting] = useState(null) // { provider, refs?: {...}, busy }
  const [testResults, setTestResults] = useState({}) // { [id]: { ok, status, models? } | { running: true } }

  const refresh = useMemo(
    () => async () => {
      setError(null)
      try {
        const data = await listProviders()
        setItems(data?.items ?? [])
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load providers')
        setItems([])
      }
    },
    [],
  )

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function onToggleEnabled(p, next) {
    try {
      await patchProvider(p.id, { enabled: next })
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Toggle failed')
    }
  }

  async function onTest(p) {
    setTestResults((r) => ({ ...r, [p.id]: { running: true } }))
    try {
      const out = await testProvider(p.id)
      setTestResults((r) => ({ ...r, [p.id]: out }))
    } catch (e) {
      setTestResults((r) => ({
        ...r,
        [p.id]: { ok: false, status: e instanceof Error ? e.message : 'unknown error' },
      }))
    } finally {
      // Refresh to pick up updated last_verified_at/status in the row.
      await refresh()
    }
  }

  function openAdd() {
    setEditing({ add: true })
  }

  function openEdit(p) {
    setEditing({ add: false, provider: p })
  }

  async function onConfirmDelete({ force }) {
    if (!deleting?.provider) return
    setDeleting((d) => ({ ...d, busy: true }))
    try {
      const res = await deleteProvider(deleting.provider.id, { force })
      if (res.ok === true) {
        setDeleting(null)
        await refresh()
      } else if (res.status === 409) {
        // Got the dependency counts — switch the dialog into force-confirm mode.
        setDeleting({ provider: deleting.provider, refs: res.references, busy: false })
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Delete failed')
      setDeleting(null)
    }
  }

  return (
    <section className="mx-auto w-full max-w-4xl space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Providers</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            OpenAI-compatible inference / embedding / reranker backends. Used by every model dropdown in the app.
          </p>
        </div>
        <Button type="button" size="sm" onClick={openAdd}>
          Add provider
        </Button>
      </header>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {items == null ? (
        <p className="text-sm text-muted-foreground">Loading providers…</p>
      ) : (() => {
        const bundled = items.filter((p) => p.bundle_group != null)
        const external = items.filter((p) => p.bundle_group == null)
        const bundledGroups = bundled.reduce((acc, p) => {
          ;(acc[p.bundle_group] ??= []).push(p)
          return acc
        }, {})

        const hasBundled = Object.keys(bundledGroups).length > 0
        const hasExternal = external.length > 0
        const hasAny = hasBundled || hasExternal

        if (!hasAny) {
          return (
            <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              No providers configured yet. Add one to start using inference, embeddings, or reranker.
            </div>
          )
        }

        return (
          <>
            {hasBundled ? (
              <div className="space-y-2">
                {Object.entries(bundledGroups).map(([groupKey, rows]) => (
                  <BundledGroupCard
                    key={groupKey}
                    groupKey={groupKey}
                    rows={rows}
                    testResults={testResults}
                    onTest={onTest}
                  />
                ))}
              </div>
            ) : null}

            {hasExternal ? (
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full table-auto text-sm">
                  <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">Name</th>
                      <th className="px-3 py-2 font-medium">Base URL</th>
                      <th className="px-3 py-2 font-medium">Key</th>
                      <th className="px-3 py-2 font-medium">Enabled</th>
                      <th className="px-3 py-2 font-medium">Verified</th>
                      <th className="px-3 py-2 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {external.map((p) => {
                      const tr = testResults[p.id]
                      return (
                        <tr key={p.id} className="border-t border-border">
                          <td className="px-3 py-2 font-medium text-foreground">{p.name}</td>
                          <td className="px-3 py-2 font-mono text-xs text-muted-foreground" title={p.base_url}>
                            {p.base_url.length > 40 ? `${p.base_url.slice(0, 40)}…` : p.base_url}
                          </td>
                          <td className="px-3 py-2">
                            <span className={cn('rounded px-1.5 py-0.5 text-xs', p.api_key === '***' ? 'bg-amber-500/15 text-amber-700 dark:text-amber-300' : 'bg-muted text-muted-foreground')}>
                              {p.api_key === '***' ? 'set' : 'none'}
                            </span>
                          </td>
                          <td className="px-3 py-2">
                            <label className="inline-flex cursor-pointer items-center gap-1.5 text-xs">
                              <input
                                type="checkbox"
                                checked={!!p.enabled}
                                onChange={(e) => void onToggleEnabled(p, e.target.checked)}
                                className="size-4 rounded border border-border bg-background text-primary"
                              />
                              {p.enabled ? 'enabled' : 'disabled'}
                            </label>
                          </td>
                          <td className="px-3 py-2 text-xs">
                            <div className="flex flex-col gap-0.5">
                              <span className={cn('inline-block w-fit rounded px-1.5 py-0.5', statusBadgeClass(p.last_verified_status))}>
                                {p.last_verified_status ?? 'never tested'}
                              </span>
                              <span className="text-muted-foreground">{relativeTime(p.last_verified_at)}</span>
                            </div>
                          </td>
                          <td className="px-3 py-2 text-right">
                            <div className="flex justify-end gap-1.5">
                              <Button type="button" size="sm" variant="outline" onClick={() => openEdit(p)}>
                                Edit
                              </Button>
                              <Button type="button" size="sm" variant="outline" onClick={() => void onTest(p)} disabled={tr?.running}>
                                {tr?.running ? 'Testing…' : 'Test'}
                              </Button>
                              <Button type="button" size="sm" variant="destructive" onClick={() => setDeleting({ provider: p, refs: null, busy: false })}>
                                Delete
                              </Button>
                            </div>
                            {tr && !tr.running ? (
                              <div className={cn('mt-1 text-left text-xs', tr.ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-rose-600 dark:text-rose-400')}>
                                {tr.ok ? `ok — ${(tr.models ?? []).length} models` : tr.status}
                                {tr.ok && tr.models?.length ? (
                                  <details className="mt-0.5">
                                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground">show ids</summary>
                                    <ul className="mt-1 list-disc pl-5 font-mono text-[11px] text-muted-foreground">
                                      {tr.models.map((m) => (
                                        <li key={m}>{m}</li>
                                      ))}
                                    </ul>
                                  </details>
                                ) : null}
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : null}
          </>
        )
      })()}

      <ProviderFormDialog
        open={!!editing}
        onOpenChange={(v) => !v && setEditing(null)}
        initial={editing?.add === false ? editing.provider : null}
        onSaved={refresh}
      />

      <DeleteConfirmDialog
        open={!!deleting}
        onOpenChange={(v) => !v && setDeleting(null)}
        provider={deleting?.provider}
        refs={deleting?.refs}
        busy={!!deleting?.busy}
        onConfirm={onConfirmDelete}
      />
    </section>
  )
}
