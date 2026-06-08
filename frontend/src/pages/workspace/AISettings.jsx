import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getCustomInstructions, putCustomInstructions } from '@/api/customInstructions.js'
import { embedAllMemories, extractMemory, getMemory, putMemory } from '@/api/memory.js'
import { createMemoryEntry, deleteMemoryEntry, listMemoryEntries } from '@/api/memoryEntries.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { toast } from 'sonner'

export default function AISettings() {
  const queryClient = useQueryClient()
  const [tab, setTab] = useState('memory')

  const { data: memoryRow, isLoading: memLoading } = useQuery({
    queryKey: ['memory'],
    queryFn: () => getMemory(),
    enabled: tab === 'memory',
    staleTime: 15_000,
  })

  const [memDraft, setMemDraft] = useState('')
  useEffect(() => {
    if (memoryRow && typeof memoryRow.content === 'string') setMemDraft(memoryRow.content)
  }, [memoryRow])

  const saveMem = useMutation({
    mutationFn: () => putMemory(memDraft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['memory'] })
      toast.success('Saved')
    },
  })

  const extractMem = useMutation({
    mutationFn: () => extractMemory(),
    onSuccess: (r) => {
      if (r?.content != null) setMemDraft(r.content)
      queryClient.invalidateQueries({ queryKey: ['memory'] })
    },
  })

  const { data: entriesRaw } = useQuery({
    queryKey: ['memory', 'entries'],
    queryFn: () => listMemoryEntries(),
    enabled: tab === 'memory',
    staleTime: 15_000,
  })
  const memoryEntries = Array.isArray(entriesRaw) ? entriesRaw : []

  const { data: globalInstrRow } = useQuery({
    queryKey: ['custom-instructions'],
    queryFn: () => getCustomInstructions(),
    enabled: tab === 'instructions',
    staleTime: 15_000,
  })

  const [gInstrDraft, setGInstrDraft] = useState('')
  useEffect(() => {
    if (globalInstrRow && typeof globalInstrRow.content === 'string') setGInstrDraft(globalInstrRow.content)
  }, [globalInstrRow])

  const [entryAdding, setEntryAdding] = useState(false)
  const [entryNewContent, setEntryNewContent] = useState('')
  const [expandedFactIds, setExpandedFactIds] = useState(() => new Set())
  const [embedResultMsg, setEmbedResultMsg] = useState(null)

  useEffect(() => {
    if (!embedResultMsg) return
    const t = window.setTimeout(() => setEmbedResultMsg(null), 5000)
    return () => window.clearTimeout(t)
  }, [embedResultMsg])

  const saveGlobalInstr = useMutation({
    mutationFn: () => putCustomInstructions(gInstrDraft),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['custom-instructions'] })
      toast.success('Saved')
    },
  })

  const addEntry = useMutation({
    mutationFn: () => createMemoryEntry(entryNewContent.trim()),
    onSuccess: () => {
      setEntryAdding(false)
      setEntryNewContent('')
      queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] })
    },
  })
  const delEntry = useMutation({
    mutationFn: (id) => deleteMemoryEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] }),
  })
  const embedAllMut = useMutation({
    mutationFn: () => embedAllMemories(),
    onSuccess: (r) => {
      const embedded = typeof r?.embedded === 'number' ? r.embedded : 0
      const total = typeof r?.total === 'number' ? r.total : embedded
      setEmbedResultMsg(`Re-embedded ${embedded} of ${total} pending fact(s).`)
      queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] })
    },
    onError: (e) => {
      setEmbedResultMsg(e instanceof Error ? e.message : String(e))
    },
  })

  function toggleFactExpanded(id) {
    setExpandedFactIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <div className="border-b border-border px-4 py-4">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">AI</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Memory, model defaults, and global instructions.
        </p>
        <div className="mt-4 flex gap-1 border-b border-border">
          {[
            { id: 'memory', label: 'Memory' },
            { id: 'instructions', label: 'Instructions' },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                tab === t.id
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">
        {tab === 'memory' && (
          <div className="flex flex-col gap-6">
            <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
              <div className="flex flex-wrap items-center justify-end gap-3">
                <div className="flex flex-wrap gap-2">
                  <Button type="button" size="sm" variant="secondary" onClick={() => setEntryAdding((a) => !a)}>
                    Add fact
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={embedAllMut.isPending}
                    onClick={() => embedAllMut.mutate()}
                  >
                    {embedAllMut.isPending ? 'Re-embedding…' : 'Re-embed all'}
                  </Button>
                </div>
              </div>
              {embedResultMsg ? (
                <p
                  className={cn(
                    'text-sm',
                    embedAllMut.isError ? 'text-destructive' : 'text-muted-foreground',
                  )}
                  role="status"
                >
                  {embedResultMsg}
                </p>
              ) : null}
              {entryAdding ? (
                <div className="rounded-lg border border-border bg-card p-4">
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">New fact</span>
                    <textarea
                      value={entryNewContent}
                      onChange={(e) => setEntryNewContent(e.target.value)}
                      rows={4}
                      className="w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                      placeholder="Something to remember…"
                    />
                  </label>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => addEntry.mutate()}
                      disabled={addEntry.isPending || !entryNewContent.trim()}
                    >
                      Save
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setEntryAdding(false)
                        setEntryNewContent('')
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : null}
              {memoryEntries.length === 0 && !entryAdding ? (
                <p className="text-sm text-muted-foreground">
                  No memory facts stored. Facts are saved automatically when you use &apos;remember that&apos; in chat,
                  or add them manually here.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {memoryEntries.map((e) => {
                    const full = e.content || ''
                    const isLong = full.length > 120
                    const display =
                      expandedFactIds.has(e.id) || !isLong ? full : `${full.slice(0, 120)}…`
                    const hasEmb = e.has_embedding === true
                    const meta = (
                      <>
                        <p className="whitespace-pre-wrap text-sm text-foreground">{display}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2">
                          <span
                            className={cn(
                              'inline-block rounded-full px-2 py-0.5 text-xs font-medium',
                              e.source === 'auto'
                                ? 'bg-secondary text-secondary-foreground'
                                : 'bg-primary/15 text-foreground',
                            )}
                          >
                            {e.source === 'auto' ? 'auto' : 'manual'}
                          </span>
                          <span
                            className="flex items-center gap-1.5 text-xs text-muted-foreground"
                            title={hasEmb ? 'Has vector embedding' : 'No embedding yet'}
                          >
                            <span
                              className={cn('size-2 shrink-0 rounded-full', hasEmb ? 'bg-primary' : 'bg-muted-foreground/45')}
                              aria-hidden
                            />
                            <span className="sr-only">{hasEmb ? 'Embedded' : 'Not embedded'}</span>
                          </span>
                        </div>
                      </>
                    )
                    return (
                      <li
                        key={e.id}
                        className="flex items-start gap-1 rounded-md border border-border bg-card px-3 py-2.5"
                      >
                        {isLong ? (
                          <button
                            type="button"
                            className="min-w-0 flex-1 rounded-sm text-left outline-none ring-ring focus-visible:ring-2"
                            onClick={() => toggleFactExpanded(e.id)}
                          >
                            {meta}
                          </button>
                        ) : (
                          <div className="min-w-0 flex-1">{meta}</div>
                        )}
                        <button
                          type="button"
                          className="shrink-0 rounded px-2 py-1 text-lg leading-none text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                          aria-label="Delete fact"
                          disabled={delEntry.isPending}
                          onClick={() => delEntry.mutate(e.id)}
                        >
                          ×
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>

            <div className="flex flex-col gap-3 border-t border-border pt-6">
              <div>
                <h2 className="text-sm font-medium text-foreground">Markdown memory</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Long-form notes (separate from the searchable facts above). Last updated applies to this editor only.
                </p>
              </div>
              {memoryRow?.updated_at && (
                <p className="text-xs text-muted-foreground">Last updated: {memoryRow.updated_at}</p>
              )}
              {memLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
              <textarea
                value={memDraft}
                onChange={(e) => setMemDraft(e.target.value)}
                rows={14}
                className="min-h-[10rem] w-full resize-y rounded-md border border-border bg-card px-3 py-2 font-mono text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                placeholder="Markdown: headings and bullet lists…"
              />
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => saveMem.mutate()} disabled={saveMem.isPending}>
                  Save
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => extractMem.mutate()}
                  disabled={extractMem.isPending}
                >
                  {extractMem.isPending ? 'Extracting…' : 'Extract from recent chat'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {tab === 'instructions' && (
          <div className="flex flex-col gap-6">
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-medium text-foreground">Global instructions</h2>
              <textarea
                value={gInstrDraft}
                onChange={(e) => setGInstrDraft(e.target.value)}
                rows={6}
                className="mb-3 w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
              />
              <Button type="button" size="sm" onClick={() => saveGlobalInstr.mutate()} disabled={saveGlobalInstr.isPending}>
                Save
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
