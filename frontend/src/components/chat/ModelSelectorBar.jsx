import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, Search } from 'lucide-react'

import { fetchOllamaModels } from '@/api/ollama.js'
import { patchChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

import { BooOpsMark } from './BooOpsMark.jsx'

const DROPDOWN_PANEL_STYLE = {
  position: 'absolute',
  top: '100%',
  left: '50%',
  transform: 'translateX(-50%)',
  zIndex: 9999,
  minWidth: 320,
  maxWidth: 'min(100vw - 1.5rem, 22rem)',
  background: 'var(--bg-panel)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
}

function formatModelSize(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return '—'
  const n = Number(bytes)
  if (n <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  const dec = v >= 10 || i === 0 ? 0 : 1
  return `${v.toFixed(dec)} ${units[i]}`
}

export function ModelSelectorBar({ className }) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState('models')
  const [q, setQ] = useState('')
  const wrapRef = useRef(null)

  const selectedModel = useAppStore((s) => s.selectedModel)
  const setSelectedModel = useAppStore((s) => s.setSelectedModel)
  const activeChatId = useAppStore((s) => s.activeChatId)

  const { data, isLoading } = useQuery({
    queryKey: ['ollama', 'models'],
    queryFn: fetchOllamaModels,
    staleTime: 60_000,
  })

  const models = useMemo(() => {
    const raw = Array.isArray(data?.models) ? data.models : []
    return raw
      .map((m) => ({
        name: typeof m?.name === 'string' ? m.name : '',
        size: m?.size,
      }))
      .filter((m) => m.name)
  }, [data])

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return models
    return models.filter((m) => m.name.toLowerCase().includes(s))
  }, [models, q])

  const displayName = selectedModel || 'Select model'

  useEffect(() => {
    if (!open) return
    function onMouseDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  async function selectModel(name) {
    setSelectedModel(name)
    setOpen(false)
    setQ('')
    if (activeChatId) {
      try {
        await patchChat(activeChatId, { model: name })
      } catch {
        /* ignore */
      }
    }
  }

  return (
    <div className={cn('flex min-w-0 items-center justify-center', className)}>
      <div ref={wrapRef} className="relative">
        <Button
          type="button"
          variant="ghost"
          className="h-9 max-w-full gap-2 px-3 font-normal text-foreground hover:bg-accent hover:text-accent-foreground"
          aria-expanded={open}
          aria-haspopup="dialog"
          onClick={() => setOpen((o) => !o)}
        >
          <span className="truncate text-sm font-medium">{displayName}</span>
          <ChevronDown className="size-4 shrink-0 opacity-70" aria-hidden />
        </Button>
        {open && (
          <div
            className="mt-1 flex flex-col gap-2 p-2"
            style={DROPDOWN_PANEL_STYLE}
            role="dialog"
            aria-label="Model selector"
          >
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search…"
                className="h-9 w-full rounded-md border border-border bg-card py-2 pl-8 pr-2 text-sm text-foreground outline-none ring-ring placeholder:text-muted-foreground focus-visible:ring-2"
              />
            </div>
            <div className="flex gap-1 border-b border-border pb-1">
              <button
                type="button"
                className={cn(
                  'flex-1 rounded-md py-1.5 text-center text-xs font-semibold uppercase tracking-wide transition-colors',
                  tab === 'models'
                    ? 'bg-secondary text-secondary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
                onClick={() => setTab('models')}
              >
                Models
              </button>
              <button
                type="button"
                className={cn(
                  'flex-1 rounded-md py-1.5 text-center text-xs font-semibold uppercase tracking-wide transition-colors',
                  tab === 'personas'
                    ? 'bg-secondary text-secondary-foreground'
                    : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                )}
                onClick={() => setTab('personas')}
              >
                Personas
              </button>
            </div>
            {tab === 'models' && (
              <div className="max-h-[min(50vh,20rem)] overflow-y-auto">
                {isLoading && (
                  <p className="px-2 py-3 text-center text-sm text-muted-foreground">Loading models…</p>
                )}
                {!isLoading && filtered.length === 0 && (
                  <p className="px-2 py-3 text-center text-sm text-muted-foreground">No models match</p>
                )}
                <ul className="flex flex-col gap-0.5">
                  {filtered.map((m) => {
                    const sel = m.name === selectedModel
                    return (
                      <li key={m.name}>
                        <button
                          type="button"
                          className={cn(
                            'flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground',
                            sel && 'bg-muted',
                          )}
                          onClick={() => selectModel(m.name)}
                        >
                          <span className="size-8 shrink-0 rounded-full border border-border bg-muted" aria-hidden />
                          <span className="min-w-0 flex-1 truncate font-medium text-foreground">{m.name}</span>
                          <span className="shrink-0 text-xs text-muted-foreground">{formatModelSize(m.size)}</span>
                          {sel && (
                            <span
                              className="size-2 shrink-0 rounded-full"
                              style={{ background: 'var(--success, var(--accent-2))' }}
                              title="Active"
                            />
                          )}
                          {sel && <Check className="size-4 shrink-0 text-primary" aria-label="Selected" />}
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
            {tab === 'personas' && (
              <div className="py-1">
                <div className="flex items-center gap-2 rounded-md border border-border bg-muted/50 px-2 py-2">
                  <BooOpsMark className="size-8 text-xs" />
                  <span className="text-sm font-medium text-foreground">BooOps (Default)</span>
                  <Check className="ml-auto size-4 shrink-0 text-primary" aria-label="Selected" />
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
