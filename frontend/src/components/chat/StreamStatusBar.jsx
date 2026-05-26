import { useEffect, useState } from 'react'

import { cn } from '@/lib/utils'

const PHASE_LABELS = {
  preparing: 'Preparing',
  rag: 'Retrieving documents',
  search: 'Searching web',
  thinking: 'Thinking',
  generating: 'Generating',
}

function formatElapsed(ms) {
  const sec = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function StreamStatusBar({ phase, startedAt, className }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!phase || !startedAt) return undefined
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [phase, startedAt])

  if (!phase || !startedAt) return null
  const label = PHASE_LABELS[phase] ?? 'Working'
  const elapsed = now - startedAt

  return (
    <div
      className={cn(
        'mb-2 flex items-center gap-2 rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground shadow-sm',
        className,
      )}
      role="status"
      aria-live="polite"
      data-testid="stream-status-bar"
    >
      <span
        className="inline-block size-2 shrink-0 animate-pulse rounded-full bg-primary"
        aria-hidden
      />
      <span className="text-foreground">{label}…</span>
      <span className="font-mono text-xs tabular-nums">{formatElapsed(elapsed)}</span>
      {phase === 'thinking' ? (
        <span className="text-xs">(CPU inference can take 1–2 min)</span>
      ) : null}
    </div>
  )
}
