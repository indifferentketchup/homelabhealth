// ──────────────────────────────────────────────────────────────────────────────
// PreFlightCard — fetches /api/system/doctor on mount + has a refresh button.
// ──────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useState } from 'react'
import { getDoctor } from '@/api/system.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function PreFlightCard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await getDoctor()
      setData(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load pre-flight')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const summary = data?.summary || { ok: 0, warn: 0, error: 0 }

  return (
    <details className="rounded-lg border border-border bg-card p-4" data-testid="preflight-card">
      <summary className="cursor-pointer text-sm font-medium text-foreground">
        Pre-flight checks
        {data ? (
          <span className="ml-2 font-mono text-xs text-muted-foreground">
            {summary.ok} ok · {summary.warn} warn · {summary.error} error
          </span>
        ) : null}
      </summary>
      <div className="mt-3 space-y-1.5">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          (data?.checks ?? []).map((c) => (
            <div key={c.name} className="flex items-start gap-2 text-sm">
              <span className={cn('font-mono',
                c.status === 'ok' && 'text-primary',
                c.status === 'warn' && 'text-secondary',
                c.status === 'error' && 'text-destructive',
              )}>
                {c.status === 'ok' ? '✓' : c.status === 'warn' ? '⚠' : '✗'}
              </span>
              <span className="font-mono text-xs text-foreground">{c.name}</span>
              <span className="text-xs text-muted-foreground">{c.detail}</span>
            </div>
          ))
        )}
        <div className="pt-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
      </div>
    </details>
  )
}
