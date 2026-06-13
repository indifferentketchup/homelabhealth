import { useCallback, useEffect, useState } from 'react'

import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

const MODEL_DISPLAY = {
  'medgemma':     { label: 'Chat',       desc: 'Answers your questions using health context' },
  'qwen-chat':    { label: 'Chat (lite)', desc: 'Smaller chat model for low-RAM systems' },
  'gemma-tasks':  { label: 'Tasks',      desc: 'Handles background jobs like summarization' },
  'qwen3-embed':    { label: 'Search',     desc: 'Finds relevant documents for your question' },
  'qwen3-reranker': { label: 'Relevance',  desc: 'Re-scores search results for accuracy' },
}

function modelLabel(id) {
  return MODEL_DISPLAY[id]?.label ?? id
}

function modelDesc(id) {
  return MODEL_DISPLAY[id]?.desc ?? id
}

export default function ModelStateSidebar({ className }) {
  const [state, setState] = useState(null)

  const fetchState = useCallback(async () => {
    try {
      const r = await fetch('/api/inference/state')
      if (!r.ok) return
      const data = await r.json()
      setState(data)
    } catch {
      /* ignore */
    }
  }, [])

  useEffect(() => {
    let stopped = false
    const poll = () => { if (!stopped) fetchState() }
    poll()
    const id = setInterval(poll, 3000)
    return () => { stopped = true; clearInterval(id) }
  }, [fetchState])

  if (!state) return null

  const { tier, budget_mib, loaded_ram_mib, budget_pct, models } = state
  const loaded = models.filter((m) => m.state === 'loaded')
  const sleeping = models.filter((m) => m.state === 'sleeping')
  const unloaded = models.filter((m) => m.state === 'unloaded')
  const unknown = models.filter((m) => m.state === 'unknown')

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

      <TooltipProvider>
      <ul className="flex flex-col gap-1">
        {loaded.map((m) => (
          <li key={`${m.provider}-${m.id}`} className="flex items-center gap-1.5">
            <span className="size-1.5 shrink-0 rounded-full bg-emerald-500" />
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex-1 text-foreground cursor-default border-b border-dotted border-muted-foreground/30">{modelLabel(m.id)}</span>
              </TooltipTrigger>
              <TooltipContent side="top"><p className="font-sans text-xs">{modelDesc(m.id)}</p><p className="font-mono text-[10px] text-muted-foreground mt-0.5">{m.id}</p></TooltipContent>
            </Tooltip>
            <span className="text-[10px] text-muted-foreground">{(m.ram_mib / 1024).toFixed(1)}G</span>
          </li>
        ))}
        {sleeping.map((m) => (
          <li key={`${m.provider}-${m.id}`} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/40" />
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex-1 cursor-default border-b border-dotted border-muted-foreground/20">{modelLabel(m.id)}</span>
              </TooltipTrigger>
              <TooltipContent side="top"><p className="font-sans text-xs">{modelDesc(m.id)}</p><p className="font-mono text-[10px] text-muted-foreground mt-0.5">{m.id}</p></TooltipContent>
            </Tooltip>
            <span className="text-[10px]">sleep</span>
          </li>
        ))}
        {unloaded.map((m) => (
          <li key={`${m.provider}-${m.id}`} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="size-1.5 shrink-0 rounded-full bg-muted-foreground/30" />
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex-1 cursor-default border-b border-dotted border-muted-foreground/20">{modelLabel(m.id)}</span>
              </TooltipTrigger>
              <TooltipContent side="top"><p className="font-sans text-xs">{modelDesc(m.id)}</p><p className="font-mono text-[10px] text-muted-foreground mt-0.5">{m.id}</p></TooltipContent>
            </Tooltip>
            <span className="text-[10px]" title="Starts on first image request">on-demand</span>
          </li>
        ))}
        {unknown.map((m) => (
          <li key={`${m.provider}-${m.id}`} className="flex items-center gap-1.5 text-muted-foreground">
            <span className="size-1.5 shrink-0 rounded-full bg-yellow-500" />
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex-1 cursor-default border-b border-dotted border-muted-foreground/20">{modelLabel(m.id)}</span>
              </TooltipTrigger>
              <TooltipContent side="top"><p className="font-sans text-xs">{modelDesc(m.id)}</p><p className="font-mono text-[10px] text-muted-foreground mt-0.5">{m.id}</p></TooltipContent>
            </Tooltip>
            <span className="text-[10px]">unavailable</span>
          </li>
        ))}
        {loaded.length === 0 && sleeping.length === 0 && unloaded.length === 0 && unknown.length === 0 && (
          <li className="italic text-muted-foreground">No models loaded</li>
        )}
      </ul>
      </TooltipProvider>
    </div>
  )
}
