import { useEffect, useState } from 'react'

import { cn } from '@/lib/utils'

export default function ModelStateSidebar({ className }) {
  const [state, setState] = useState(null)

  useEffect(() => {
    let stopped = false
    async function poll() {
      try {
        const r = await fetch('/api/inference/state')
        if (!r.ok) return
        const data = await r.json()
        if (!stopped) setState(data)
      } catch {
        /* ignore */
      }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { stopped = true; clearInterval(id) }
  }, [])

  if (!state) return null

  const { tier, budget_mib, loaded_ram_mib, budget_pct, models } = state
  const loaded = models.filter((m) => m.state === 'loaded')
  const sleeping = models.filter((m) => m.state === 'sleeping')

  const barState = budget_pct > 90 ? 'critical' : budget_pct > 70 ? 'warn' : 'ok'
  const barColor = {
    ok: 'bg-primary',
    warn: 'bg-yellow-500',
    critical: 'bg-destructive',
  }[barState]

  return (
    <div className={cn('flex flex-col gap-2 rounded-md border border-border bg-card p-3 text-xs font-mono', className)}>
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Inference</span>
        <span className="text-[10px] text-muted-foreground">{tier}</span>
      </div>

      <div className="space-y-1">
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className={cn('h-full transition-all duration-300', barColor)}
            style={{ width: `${Math.min(100, budget_pct)}%` }}
          />
        </div>
        <div className="text-right text-[10px] text-muted-foreground">
          {(loaded_ram_mib / 1024).toFixed(1)}G / {Math.round(budget_mib / 1024)}G
        </div>
      </div>

      <ul className="flex flex-col gap-1">
        {loaded.map((m) => (
          <li key={`${m.provider}-${m.id}`} className="flex items-center gap-1.5">
            <span className="size-1.5 shrink-0 rounded-full bg-emerald-500" />
            <span className="flex-1 text-foreground">{m.id}</span>
            <span className="text-[10px] text-muted-foreground">{(m.ram_mib / 1024).toFixed(1)}G</span>
          </li>
        ))}
        {sleeping.map((m) => (
          <li key={`${m.provider}-${m.id}`} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/40" />
            <span className="flex-1">{m.id}</span>
            <span className="text-[10px]">sleep</span>
          </li>
        ))}
        {loaded.length === 0 && sleeping.length === 0 && (
          <li className="italic text-muted-foreground">No models loaded</li>
        )}
      </ul>
    </div>
  )
}
