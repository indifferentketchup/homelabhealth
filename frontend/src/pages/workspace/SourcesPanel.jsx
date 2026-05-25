import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FileStack, Upload } from 'lucide-react'

import { listWorkspaces } from '@/api/workspaces.js'
import { deleteSource, listSources, uploadSource } from '@/api/sources.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

function EmbeddingStatusDot({ status }) {
  const s = status ?? ''
  const cls =
    s === 'complete'
      ? 'bg-primary'
      : s === 'error'
        ? 'bg-destructive'
        : s === 'pending' || s === 'processing'
          ? 'bg-amber-500'
          : 'bg-muted-foreground/60'
  return (
    <span
      className={cn('size-2 shrink-0 rounded-full', cls)}
      title={s || 'unknown'}
      aria-hidden
    />
  )
}

export function SourcesPanel({ chatId, workspaceId }) {
  const queryClient = useQueryClient()
  const fileRef = useRef(null)

  const [uploading, setUploading] = useState(false)
  const [uploadQueue, setUploadQueue] = useState([])
  const [status, setStatus] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editName, setEditName] = useState('')
  const [viewingSource, setViewingSource] = useState(null)
  const [viewContent, setViewContent] = useState('')
  const [viewLoading, setViewLoading] = useState(false)
  const [ctx, setCtx] = useState(null)
  const ctxRef = useRef(null)

  const { data: workspacesPack } = useQuery({
    queryKey: ['workspaces', 'list'],
    queryFn: () => listWorkspaces(),
    staleTime: 30_000,
  })
  const workspaces = Array.isArray(workspacesPack?.items) ? workspacesPack.items : []

  const effectiveWorkspaceId = workspaceId ?? null

  const workspaceName = workspaces.find(w => w.id === effectiveWorkspaceId)?.name || 'None'

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['sources', effectiveWorkspaceId],
    queryFn: () => listSources(effectiveWorkspaceId),
    enabled: Boolean(effectiveWorkspaceId),
    refetchInterval: (q) => {
      const rows = q.state.data
      if (!Array.isArray(rows)) return false
      return rows.some((r) => r.embedding_status === 'processing' || r.embedding_status === 'pending')
        ? 2000
        : false
    },
  })

  useEffect(() => {
    if (!ctx) return
    function onKey(e) { if (e.key === 'Escape') setCtx(null) }
    function onClick(e) { if (ctxRef.current && !ctxRef.current.contains(e.target)) setCtx(null) }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onClick) }
  }, [ctx])

  function onSourceContextMenu(e, src) {
    e.preventDefault()
    e.stopPropagation()
    setCtx({ x: e.clientX, y: e.clientY, source: src })
  }

  function startRename(src) {
    setCtx(null)
    setEditingId(src.id)
    setEditName(src.name)
  }

  async function confirmDelete(src) {
    setCtx(null)
    if (!window.confirm(`Remove source "${src.name}"?`)) return
    try {
      await deleteSource(src.id)
      await queryClient.invalidateQueries({ queryKey: ['sources', effectiveWorkspaceId] })
    } catch {
      setStatus('Delete failed')
    }
  }

  async function onUpload(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (!files.length || !effectiveWorkspaceId) return
    setUploading(true)
    setStatus('')
    const queue = files.map(f => ({ name: f.name, status: 'pending' }))
    setUploadQueue(queue)
    for (let i = 0; i < files.length; i++) {
      setUploadQueue(prev => prev.map((item, idx) =>
        idx === i ? { ...item, status: 'uploading' } : item
      ))
      try {
        const res = await uploadSource(files[i], effectiveWorkspaceId)
        const result = res?.error ? 'error' : res?.status === 'already_exists' ? 'exists' : 'done'
        setUploadQueue(prev => prev.map((item, idx) =>
          idx === i ? { ...item, status: result } : item
        ))
      } catch {
        setUploadQueue(prev => prev.map((item, idx) =>
          idx === i ? { ...item, status: 'error' } : item
        ))
      }
    }
    await queryClient.invalidateQueries({ queryKey: ['sources', effectiveWorkspaceId] })
    setUploading(false)
    setTimeout(() => setUploadQueue([]), 5000)
  }

  return (
    <aside className="flex h-full min-h-0 w-full min-w-0 shrink-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="border-b border-sidebar-border">
        <div className="flex w-full items-center justify-center overflow-hidden px-2 py-1.5">
          <span className="fs-nav truncate text-center font-semibold uppercase tracking-wide text-muted-foreground">
            Sources
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-2 p-2">
        <input
          ref={fileRef}
          type="file"
          multiple
          accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.tiff,.bmp,text/plain,text/markdown,application/pdf,image/*"
          className="sr-only"
          disabled={uploading || !effectiveWorkspaceId}
          onChange={(ev) => void onUpload(ev)}
        />
        <Button
          type="button"
          className="fs-nav min-w-0 w-full justify-start gap-2"
          disabled={uploading || !effectiveWorkspaceId}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="size-4 shrink-0" />
          <span>Add source</span>
        </Button>

        <p className="fs-nav px-2 text-muted-foreground truncate">Workspace: <span className="font-medium text-foreground">{workspaceName}</span></p>

        {status ? <p className="fs-nav text-muted-foreground">{status}</p> : null}
        {uploadQueue.length > 0 && (
          <div className="flex flex-col gap-1">
            {uploadQueue.map((item, i) => (
              <div key={i} className="flex items-center gap-2 rounded px-2 py-1 text-xs">
                <span className={cn(
                  'size-2 shrink-0 rounded-full',
                  item.status === 'done' ? 'bg-primary' :
                  item.status === 'uploading' ? 'bg-amber-500 animate-pulse' :
                  item.status === 'error' ? 'bg-destructive' :
                  item.status === 'exists' ? 'bg-muted-foreground' :
                  'bg-muted-foreground/40'
                )} />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{item.name}</span>
                <span className="shrink-0 text-muted-foreground/70">
                  {item.status === 'uploading' ? 'Uploading…' :
                   item.status === 'done' ? '✓' :
                   item.status === 'error' ? '✗' :
                   item.status === 'exists' ? 'Exists' :
                   'Waiting'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="mx-2 border-t border-sidebar-border" />

      <ScrollArea className="min-h-0 flex-1 px-2">
        <div className="flex flex-col gap-1 pb-2">
          {isLoading && <p className="fs-nav px-2 text-muted-foreground">Loading…</p>}
          {!isLoading && sources.length === 0 && effectiveWorkspaceId && (
            <p className="fs-nav px-2 text-muted-foreground">No sources yet.</p>
          )}
          {sources.map((src) => {
            const ready = src.embedding_status === 'complete'
            return (
              <div
                key={src.id}
                className="group flex w-full items-stretch gap-1 rounded-md border border-transparent py-0.5 hover:border-sidebar-border hover:bg-sidebar-accent/30"
                title={src.name}
                onContextMenu={(e) => onSourceContextMenu(e, src)}
              >
                <div className="flex min-w-0 flex-1 items-start gap-2 rounded-md px-1 py-1.5">
                  <span className="min-w-0 flex-1">
                    <span className="fs-nav flex items-center gap-1.5 font-medium text-foreground">
                      <EmbeddingStatusDot status={src.embedding_status} />
                      <FileStack className="size-3.5 shrink-0 opacity-70" aria-hidden />
                      {editingId === src.id ? (
                        <input
                          type="text"
                          className="fs-nav w-full rounded border border-border bg-background px-1 py-0.5 text-sm text-foreground outline-none focus:ring-1 focus:ring-ring"
                          value={editName}
                          autoFocus
                          onChange={e => setEditName(e.target.value)}
                          onBlur={async () => {
                            if (editName.trim() && editName.trim() !== src.name) {
                              const { patchSource } = await import('@/api/sources.js')
                              await patchSource(src.id, { name: editName.trim() })
                              await queryClient.invalidateQueries({ queryKey: ['sources', effectiveWorkspaceId] })
                            }
                            setEditingId(null)
                          }}
                          onKeyDown={e => {
                            if (e.key === 'Enter') e.target.blur()
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                        />
                      ) : (
                        <button
                          type="button"
                          className="line-clamp-2 text-left hover:underline"
                          onClick={async () => {
                            setViewingSource(src)
                            setViewLoading(true)
                            try {
                              const { getSourceContent } = await import('@/api/sources.js')
                              const res = await getSourceContent(src.id)
                              setViewContent(res.content || '(empty)')
                            } catch {
                              setViewContent('(could not load content)')
                            } finally {
                              setViewLoading(false)
                            }
                          }}
                        >
                          {src.name}
                        </button>
                      )}
                    </span>
                    {src.embedding_status !== 'complete' && (
                      <span className="fs-nav block text-muted-foreground">
                        {src.embedding_status === 'processing' ? 'Processing…' : src.embedding_status === 'pending' ? 'Pending…' : src.embedding_status === 'error' ? 'Error' : src.embedding_status || ''}
                      </span>
                    )}
                  </span>
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-6 shrink-0 px-1.5 text-xs text-muted-foreground hover:text-primary"
                    title="Attach to chat"
                    disabled={!ready}
                    onClick={() => {
                      window.dispatchEvent(new CustomEvent('hlh:attach-source', {
                        detail: { name: src.name, id: src.id },
                      }))
                    }}
                  >
                    Send to Chat
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      </ScrollArea>

      {ctx && (
        <div
          ref={ctxRef}
          role="menu"
          className="fixed z-50 min-w-[10rem] rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
          style={{
            left: Math.min(ctx.x, window.innerWidth - 180),
            top: Math.min(ctx.y, window.innerHeight - 120),
          }}
          onClick={(e) => e.stopPropagation()}
          onContextMenu={(e) => e.preventDefault()}
        >
          <button
            type="button"
            role="menuitem"
            className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left outline-none hover:bg-accent hover:text-accent-foreground"
            onClick={() => startRename(ctx.source)}
          >
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left text-destructive outline-none hover:bg-destructive/10"
            onClick={() => confirmDelete(ctx.source)}
          >
            Delete
          </button>
        </div>
      )}

      {viewingSource && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setViewingSource(null)}>
          <div className="mx-4 flex max-h-[80vh] w-full max-w-2xl flex-col rounded-lg border border-border bg-background shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h3 className="text-sm font-semibold text-foreground truncate">{viewingSource.name}</h3>
              <button type="button" onClick={() => setViewingSource(null)} className="text-muted-foreground hover:text-foreground text-lg">×</button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              {viewLoading ? (
                <p className="text-sm text-muted-foreground">Loading…</p>
              ) : (
                <pre className="whitespace-pre-wrap text-sm text-foreground font-mono leading-relaxed">{viewContent}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </aside>
  )
}
