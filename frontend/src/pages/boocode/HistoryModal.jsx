import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, Sparkles, Trash2, X } from 'lucide-react'

import { listHistory, readHistory, renameHistory, deleteHistory } from '@/api/history.js'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { friendlyErr } from '@/lib/friendlyErr.js'

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function humanTime(epoch) {
  const d = new Date(epoch * 1000)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export default function HistoryModal({ open, onClose, kind, dawId, dawName }) {
  const queryClient = useQueryClient()

  const [viewing, setViewing] = useState(null) // { file, content } when viewing
  const [pendingDelete, setPendingDelete] = useState(null) // filename awaiting confirm
  const [renamingSet, setRenamingSet] = useState(new Set()) // filenames currently renaming
  const [inlineErrors, setInlineErrors] = useState({}) // filename -> error string
  const [deletingSet, setDeletingSet] = useState(new Set()) // filenames currently deleting

  const queryKey = ['history', kind, dawId]

  const { data, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () => listHistory(kind, { dawId }),
    enabled: Boolean(open && dawId),
  })

  const title =
    kind === 'chats'
      ? `Chat History — ${dawName}`
      : `Terminal History — ${dawName}`

  const kindLabel = kind === 'chats' ? 'chats' : 'terminal sessions'

  async function handleView(file) {
    try {
      const result = await readHistory(kind, { dawId, file })
      // result may be { content: '...' } or a raw string depending on backend
      const content = typeof result === 'string' ? result : (result?.content ?? JSON.stringify(result, null, 2))
      setViewing({ file, content })
    } catch (err) {
      setInlineErrors((prev) => ({ ...prev, [file]: friendlyErr(err) }))
    }
  }

  async function handleRename(file) {
    setRenamingSet((prev) => new Set([...prev, file]))
    setInlineErrors((prev) => {
      const next = { ...prev }
      delete next[file]
      return next
    })
    try {
      await renameHistory(kind, { dawId, oldName: file, newName: '__ai__' })
      await queryClient.invalidateQueries({ queryKey })
    } catch (err) {
      const msg = friendlyErr(err)
      setInlineErrors((prev) => ({ ...prev, [file]: msg }))
    } finally {
      setRenamingSet((prev) => {
        const next = new Set(prev)
        next.delete(file)
        return next
      })
    }
  }

  async function handleDeleteConfirm(file) {
    setDeletingSet((prev) => new Set([...prev, file]))
    try {
      await deleteHistory(kind, { dawId, file })
      setPendingDelete(null)
      await queryClient.invalidateQueries({ queryKey })
    } catch (err) {
      setInlineErrors((prev) => ({ ...prev, [file]: friendlyErr(err) }))
      setPendingDelete(null)
    } finally {
      setDeletingSet((prev) => {
        const next = new Set(prev)
        next.delete(file)
        return next
      })
    }
  }

  function handleClose() {
    setViewing(null)
    setPendingDelete(null)
    setRenamingSet(new Set())
    setDeletingSet(new Set())
    setInlineErrors({})
    onClose()
  }

  const files = Array.isArray(data?.files) ? data.files : []

  return (
    <>
      {/* Main list dialog */}
      <Dialog open={open && !viewing} onOpenChange={(v) => { if (!v) handleClose() }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>

          {isLoading && (
            <p className="py-6 text-center text-sm text-muted-foreground">Loading…</p>
          )}

          {isError && (
            <p className="py-6 text-center text-sm text-destructive">Failed to load history.</p>
          )}

          {!isLoading && !isError && files.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No saved {kindLabel} yet.
            </p>
          )}

          {!isLoading && !isError && files.length > 0 && (
            <ScrollArea className="max-h-[60vh]">
              <ul className="flex flex-col gap-1 pr-2">
                {files.map((entry) => {
                  const file = typeof entry === 'string' ? entry : entry.name
                  const mtime = entry.mtime ?? null
                  const size = entry.size ?? null
                  const isRenaming = renamingSet.has(file)
                  const isDeleting = deletingSet.has(file)
                  const isPendingDel = pendingDelete === file
                  const rowError = inlineErrors[file]

                  return (
                    <li
                      key={file}
                      className="rounded-md border border-border bg-card/50 p-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <p className="truncate font-mono text-xs text-foreground">{file}</p>
                          <p className="mt-0.5 text-xs text-muted-foreground">
                            {mtime != null ? humanTime(mtime) : ''}
                            {mtime != null && size != null ? ' · ' : ''}
                            {size != null ? humanSize(size) : ''}
                          </p>
                        </div>

                        {!isPendingDel && (
                          <div className="flex shrink-0 gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              title="View"
                              onClick={() => handleView(file)}
                              disabled={isRenaming || isDeleting}
                            >
                              <Eye className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              title="Rename (AI)"
                              onClick={() => handleRename(file)}
                              disabled={isRenaming || isDeleting}
                            >
                              {isRenaming ? (
                                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
                              ) : (
                                <Sparkles className="h-3.5 w-3.5" />
                              )}
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              title="Delete"
                              onClick={() => setPendingDelete(file)}
                              disabled={isRenaming || isDeleting}
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                        )}

                        {isPendingDel && (
                          <div className="flex shrink-0 items-center gap-2">
                            <span className="text-xs text-muted-foreground">Delete?</span>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-6 px-2 text-xs"
                              onClick={() => setPendingDelete(null)}
                              disabled={isDeleting}
                            >
                              Cancel
                            </Button>
                            <Button
                              variant="destructive"
                              size="sm"
                              className="h-6 px-2 text-xs"
                              onClick={() => handleDeleteConfirm(file)}
                              disabled={isDeleting}
                            >
                              {isDeleting ? 'Deleting…' : 'Confirm'}
                            </Button>
                          </div>
                        )}
                      </div>

                      {rowError && (
                        <p className="mt-1.5 text-xs text-destructive">{rowError}</p>
                      )}
                    </li>
                  )
                })}
              </ul>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>

      {/* View dialog */}
      <Dialog open={Boolean(viewing)} onOpenChange={(v) => { if (!v) setViewing(null) }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <div className="flex items-center justify-between gap-2">
              <DialogTitle className="truncate font-mono text-sm">
                {viewing?.file ?? ''}
              </DialogTitle>
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7 shrink-0"
                onClick={() => setViewing(null)}
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </DialogHeader>
          <ScrollArea className="max-h-[70vh]">
            <pre className="whitespace-pre-wrap break-words font-mono text-xs text-foreground">
              {viewing?.content ?? ''}
            </pre>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  )
}
