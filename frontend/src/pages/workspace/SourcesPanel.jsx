import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { FileStack, Trash2, Upload } from 'lucide-react'

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
  const [status, setStatus] = useState('')
  const [editingId, setEditingId] = useState(null)
  const [editName, setEditName] = useState('')

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

  async function onUpload(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (!files.length || !effectiveWorkspaceId) return
    setUploading(true)
    setStatus('')
    try {
      const res = await uploadSource(files[0], effectiveWorkspaceId)
      if (files.length === 1) {
        if (res?.status === 'already_exists') {
          setStatus('Already ingested (same file hash).')
        } else {
          setStatus(`Ingesting ${files[0].name}…`)
        }
      } else {
        const { uploadSources } = await import('@/api/sources.js')
        const multi = await uploadSources(files, effectiveWorkspaceId)
        const count = multi?.sources?.length || 1
        setStatus(`Ingesting ${count} file${count > 1 ? 's' : ''}…`)
      }
      await queryClient.invalidateQueries({ queryKey: ['sources', effectiveWorkspaceId] })
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
      await queryClient.invalidateQueries({ queryKey: ['sources', effectiveWorkspaceId] })
    } catch {
      setStatus('Delete failed')
    }
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
                title={src.name}
                className="group flex w-full items-stretch gap-1 rounded-md border border-transparent py-0.5 hover:border-sidebar-border hover:bg-sidebar-accent/30"
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
                        <span
                          className="line-clamp-2 cursor-pointer"
                          onDoubleClick={() => { setEditingId(src.id); setEditName(src.name) }}
                        >
                          {src.name}
                        </span>
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
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    title="Remove source"
                    onClick={() => void onDeleteSource(src.id, src.name)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      </ScrollArea>
    </aside>
  )
}
