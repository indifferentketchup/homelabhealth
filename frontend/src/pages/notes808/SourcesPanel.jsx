import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, FileStack, Trash2, Upload } from 'lucide-react'

import { getChatSourceSelection, setChatSourceSelection } from '@/api/chats.js'
import { listDaws } from '@/api/daws.js'
import { deleteSource, listSources, uploadSource } from '@/api/sources.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store/index.js'

function EmbeddingStatusDot({ status }) {
  const s = status ?? ''
  const cls =
    s === 'complete'
      ? 'bg-green-500'
      : s === 'error'
        ? 'bg-red-500'
        : s === 'pending' || s === 'processing'
          ? 'bg-amber-400'
          : 'bg-muted-foreground/60'
  return (
    <span
      className={cn('size-2 shrink-0 rounded-full', cls)}
      title={s || 'unknown'}
      aria-hidden
    />
  )
}

export function SourcesPanel({ chatId, dawId }) {
  const queryClient = useQueryClient()
  const fileRef = useRef(null)
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)

  const [uploading, setUploading] = useState(false)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [status, setStatus] = useState('')
  const [libraryOpen, setLibraryOpen] = useState(true)

  const { data: dawsPack } = useQuery({
    queryKey: ['daws', 'list', '808notes'],
    queryFn: () => listDaws('808notes'),
    staleTime: 30_000,
  })
  const daws = Array.isArray(dawsPack?.items) ? dawsPack.items : []

  const effectiveDawId = dawId ?? null

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['sources', effectiveDawId],
    queryFn: () => listSources(effectiveDawId),
    enabled: Boolean(effectiveDawId),
    refetchInterval: (q) => {
      const rows = q.state.data
      if (!Array.isArray(rows)) return false
      return rows.some((r) => r.embedding_status === 'processing' || r.embedding_status === 'pending')
        ? 2000
        : false
    },
  })

  useEffect(() => {
    if (!chatId) {
      setSelectedIds(new Set())
      return
    }
    let cancelled = false
    ;(async () => {
      try {
        const pack = await getChatSourceSelection(chatId)
        const ids = Array.isArray(pack?.source_ids) ? pack.source_ids : []
        if (!cancelled) setSelectedIds(new Set(ids.map(String)))
      } catch {
        if (!cancelled) setSelectedIds(new Set())
      }
    })()
    return () => {
      cancelled = true
    }
  }, [chatId])

  async function syncSelection(nextSet) {
    setSelectedIds(nextSet)
    if (chatId) {
      try {
        await setChatSourceSelection(
          chatId,
          Array.from(nextSet).map((id) => id),
        )
      } catch {
        setStatus('Could not save source selection')
      }
    }
  }

  function toggleSource(id) {
    const next = new Set(selectedIds)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    void syncSelection(next)
  }

  async function onUpload(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !effectiveDawId) return
    setUploading(true)
    setStatus('')
    try {
      const res = await uploadSource(file, effectiveDawId)
      if (res?.status === 'already_exists') {
        setStatus('Already ingested (same file hash).')
      } else {
        setStatus(`Ingesting ${file.name}…`)
      }
      await queryClient.invalidateQueries({ queryKey: ['sources', effectiveDawId] })
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function onDeleteSource(id, name) {
    if (!window.confirm(`Remove source "${name}"?`)) return
    try {
      await deleteSource(id)
      const next = new Set(selectedIds)
      next.delete(id)
      setSelectedIds(next)
      if (chatId) {
        await setChatSourceSelection(chatId, Array.from(next))
      }
      await queryClient.invalidateQueries({ queryKey: ['sources', effectiveDawId] })
    } catch {
      setStatus('Delete failed')
    }
  }

  const completeSourceIds = useMemo(() => {
    return sources
      .filter((s) => s.embedding_status === 'complete')
      .map((s) => s.id)
  }, [sources])

  const allSelected = completeSourceIds.length > 0 && completeSourceIds.every((id) => selectedIds.has(id))

  return (
    <aside className="flex h-full min-h-0 w-full min-w-0 shrink-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="border-b border-sidebar-border">
        <div className="flex min-h-16 w-full items-center justify-center overflow-hidden px-2 py-2">
          <span className="fs-nav truncate text-center font-semibold uppercase tracking-wide text-muted-foreground">
            Sources
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2 p-2">
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf"
          className="sr-only"
          disabled={uploading || !effectiveDawId}
          onChange={(ev) => void onUpload(ev)}
        />
        <Button
          type="button"
          className="fs-nav min-w-0 w-full justify-start gap-2"
          disabled={uploading || !effectiveDawId}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="size-4 shrink-0" />
          <span>Add source</span>
        </Button>

        <label className="fs-nav block text-muted-foreground">DAW</label>
        <select
          className="fs-input h-9 w-full rounded-md border border-sidebar-border bg-card px-2 text-foreground outline-none ring-sidebar-ring focus-visible:ring-2"
          value={effectiveDawId || ''}
          onChange={(e) => {
            const v = e.target.value || null
            setActiveDawId(v)
            void syncSelection(new Set())
          }}
        >
          <option value="">Select…</option>
          {daws.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>

        {status ? <p className="fs-nav text-muted-foreground">{status}</p> : null}
        {!effectiveDawId ? (
          <p className="fs-nav text-amber-600/90 dark:text-amber-400/90">Pick a DAW to manage sources.</p>
        ) : null}
      </div>

      <div className="mx-2 border-t border-sidebar-border" />

      <ScrollArea className="min-h-0 flex-1 px-2">
        <div className="flex flex-col gap-1 pb-2">
          <button
            type="button"
            onClick={() => setLibraryOpen((o) => !o)}
            className="fs-nav mt-1 flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left font-medium uppercase tracking-wide text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
          >
            <div className="flex items-center gap-2">
              <span>Library</span>
              {chatId && completeSourceIds.length > 0 && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    if (allSelected) {
                      void syncSelection(new Set())
                    } else {
                      void syncSelection(new Set(completeSourceIds))
                    }
                  }}
                  className="text-xs text-muted-foreground underline-offset-2 hover:underline hover:text-foreground"
                >
                  {allSelected ? 'none' : 'all'}
                </button>
              )}
            </div>
            <ChevronDown
              className={cn(
                'size-4 shrink-0 transition-transform duration-150',
                !libraryOpen && '-rotate-90',
              )}
              aria-hidden
            />
          </button>

          <div className={cn(!libraryOpen && 'hidden')}>
            {isLoading && <p className="fs-nav px-2 text-muted-foreground">Loading…</p>}
            {!isLoading && sources.length === 0 && effectiveDawId && (
              <p className="fs-nav px-2 text-muted-foreground">No sources yet.</p>
            )}
            {sources.map((src) => {
              const ready = src.embedding_status === 'complete'
              const on = selectedIds.has(src.id)
              return (
                <div
                  key={src.id}
                  className="group flex w-full items-stretch gap-1 rounded-md border border-transparent py-0.5 hover:border-sidebar-border hover:bg-sidebar-accent/30"
                >
                  <label
                    className={cn(
                      'flex min-w-0 flex-1 cursor-pointer items-start gap-2 rounded-md px-1 py-1.5',
                      !ready ? 'cursor-not-allowed opacity-60' : '',
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-1.5 size-3.5 shrink-0"
                      checked={on}
                      disabled={!ready}
                      onChange={() => ready && toggleSource(src.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="fs-nav flex items-center gap-1.5 font-medium text-foreground">
                        <EmbeddingStatusDot status={src.embedding_status} />
                        <FileStack className="size-3.5 shrink-0 opacity-70" aria-hidden />
                        <span className="line-clamp-2">{src.name}</span>
                      </span>
                      <span className="fs-nav block text-muted-foreground">
                        {src.chunk_count ?? 0} chunks
                        {src.embedding_status ? ` · ${src.embedding_status}` : ''}
                      </span>
                    </span>
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                    title="Remove source"
                    onClick={() => void onDeleteSource(src.id, src.name)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              )
            })}
          </div>
        </div>
      </ScrollArea>

      {!chatId ? (
        <div className="mt-auto border-t border-sidebar-border p-2">
          <p className="fs-nav text-muted-foreground">
            Open or start a chat to attach sources for RAG.
          </p>
        </div>
      ) : null}
    </aside>
  )
}
