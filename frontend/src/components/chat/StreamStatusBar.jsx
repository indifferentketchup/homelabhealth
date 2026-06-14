import { useEffect, useState } from 'react'

import { cn } from '@/lib/utils'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { Badge } from '@/components/ui/badge'

const PHASE_CONFIG = {
  preparing:  { label: 'Preparing',            icon: '⏳' },
  loading:    { label: (m) => `Loading ${m || 'model'}`, icon: '⏳' },
  ready:      { label: (m) => `${m || 'Model'} ready`, icon: '✅' },
  unloading:  { label: (m) => `Unloading ${m || 'model'}`, icon: '🗑️' },
  rag:        { label: 'Retrieving documents',  icon: '🔄' },
  search:     { label: 'Searching web',         icon: '🔍' },
  embedding:  { label: 'Embedding query',       icon: '🔄' },
  searching:  { label: 'Searching records',     icon: '🔄' },
  reranking:  { label: 'Reranking results',     icon: '🔄' },
  thinking:   { label: 'Thinking',              icon: '🧠' },
  generating: { label: 'Generating',            icon: '💬' },
}

function phaseLabel(phase, model) {
  const cfg = PHASE_CONFIG[phase]
  if (!cfg) return 'Working'
  return typeof cfg.label === 'function' ? cfg.label(model) : cfg.label
}

function formatElapsed(ms) {
  const sec = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function formatEstimate(ms) {
  if (!ms || ms <= 0) return null
  const sec = Math.max(1, Math.round(ms / 1000))
  return `~${sec}s`
}

export function StreamStatusBar({ phase, startedAt, pipelineEvents = [], className }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!phase || !startedAt) return undefined
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [phase, startedAt])

  if (!phase || !startedAt) return null

  const completedStages = pipelineEvents.filter(
    (e) => e.phase !== phase && e.phase !== 'preparing' && e.phase !== 'ready',
  )
  const currentEvent = pipelineEvents.findLast((e) => e.phase === phase)
  const estimateMs = currentEvent?.estimate_ms
  const currentModel = currentEvent?.model
  const elapsed = now - startedAt

  return (
    <div className={cn('animate-message-in mb-2 flex flex-col gap-1', className)}>
      <div role="status" aria-live="polite" data-testid="stream-status-bar">
        {completedStages.length > 0 && (
          <Collapsible>
            <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground/70 hover:text-muted-foreground">
              <span className="text-[10px]" aria-hidden>&#9658;</span>
              {completedStages.length} step{completedStages.length !== 1 ? 's' : ''} completed
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="mt-1 flex flex-wrap gap-1">
                {completedStages.map((e, i) => (
                  <Badge key={e.phase + '-' + i} variant="outline" className="gap-1 text-xs">
                    <span aria-hidden>&#10003;</span>
                    {phaseLabel(e.phase, e.model)}
                  </Badge>
                ))}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}
        <div
          className="flex flex-col gap-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground shadow-sm"
        >
          <div className="flex items-center gap-2">
            <span className="inline-block size-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden />
            <span className="text-foreground">{phaseLabel(phase, currentModel)}…</span>
            <span className="ml-auto flex items-center gap-2">
              {estimateMs ? (
                <span className="text-xs text-muted-foreground/60">{formatEstimate(estimateMs)}</span>
              ) : null}
              <span className="font-mono text-xs tabular-nums">{formatElapsed(elapsed)}</span>
            </span>
          </div>
          {phase === 'thinking' ? (
            <span className="text-xs">(CPU inference can take 1-2 min)</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}
