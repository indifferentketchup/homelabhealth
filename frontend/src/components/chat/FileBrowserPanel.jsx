import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, File, Folder, Loader2, X } from 'lucide-react'

import { dubdriveLs, dubdriveRead } from '@/api/dubdrive.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

const DEFAULT_ROOT = '/HomeLabRepos/'

function ensureDirSlash(p) {
  if (!p) return '/'
  return p.endsWith('/') ? p : `${p}/`
}

function parentDirectoryPath(path) {
  const s = path.replace(/\/+$/, '')
  if (!s) return '/'
  const i = s.lastIndexOf('/')
  if (i <= 0) return '/'
  return `${s.slice(0, i + 1)}`
}

function isDirItem(item) {
  const t = (item?.type || '').toLowerCase()
  return t === 'dir' || t === 'directory' || Boolean(item?.is_dir || item?.isDir)
}

export function FileBrowserPanel({ isOpen, onClose, onFileSelect, dawSyncFolder = null }) {
  const rootPath = useMemo(() => {
    const raw = (dawSyncFolder != null && String(dawSyncFolder).trim()) || DEFAULT_ROOT
    return ensureDirSlash(raw)
  }, [dawSyncFolder])

  const [currentPath, setCurrentPath] = useState(rootPath)
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!isOpen) return
    setCurrentPath(rootPath)
  }, [isOpen, rootPath])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await dubdriveLs(currentPath.replace(/\/+$/, ''))
      const rows = Array.isArray(data) ? data : []
      const base = currentPath.endsWith('/') ? currentPath : `${currentPath}/`
      const normalized = rows
        .map((row) => {
          if (!row || typeof row !== 'object') return null
          const nameRaw = row.name != null ? String(row.name) : ''
          let fullPath = row.path != null ? String(row.path) : ''
          if (!fullPath && nameRaw) {
            fullPath = `${base.replace(/\/+$/, '')}/${nameRaw.replace(/^\/*/, '')}`
          }
          if (!nameRaw && !fullPath) return null
          const dir = isDirItem(row)
          const name =
            nameRaw || fullPath.replace(/\/+$/, '').split('/').filter(Boolean).pop() || '?'
          return {
            name,
            path: dir ? ensureDirSlash(fullPath) : fullPath,
            type: dir ? 'dir' : 'file',
            size: row.size,
          }
        })
        .filter(Boolean)
      normalized.sort((a, b) => {
        const ad = a.type === 'dir'
        const bd = b.type === 'dir'
        if (ad !== bd) return ad ? -1 : 1
        return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
      })
      setItems(normalized)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [currentPath])

  useEffect(() => {
    if (!isOpen) return
    void load()
  }, [isOpen, load])

  const breadcrumbs = useMemo(() => {
    const parts = currentPath.split('/').filter(Boolean)
    let acc = '/'
    return parts.map((seg) => {
      acc = `${acc}${seg}/`
      return { label: seg, path: acc }
    })
  }, [currentPath])

  const canGoUp = parentDirectoryPath(currentPath) !== currentPath

  async function onEntryClick(entry) {
    if (entry.type === 'dir') {
      setCurrentPath(ensureDirSlash(entry.path))
      return
    }
    setReading(true)
    try {
      const content = await dubdriveRead(entry.path)
      const text = typeof content === 'string' ? content : JSON.stringify(content, null, 2)
      onFileSelect?.(entry.name, entry.path, text)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setReading(false)
    }
  }

  if (!isOpen) return null

  const busy = loading || reading

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-30 bg-background/70"
        aria-label="Close file browser"
        onClick={onClose}
      />
      <div
        className="fixed inset-y-0 right-0 z-40 flex h-full w-[min(100vw,420px)] min-w-[280px] shadow-[var(--glow)]"
        role="dialog"
        aria-modal="true"
        aria-label="File browser"
      >
        <aside className="flex h-full min-h-0 w-full min-w-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground">
          <div className="border-b border-sidebar-border">
            <div className="flex min-h-16 w-full items-center justify-between gap-2 overflow-hidden px-2 py-2">
              <span className="fs-nav truncate text-center font-semibold uppercase tracking-wide text-muted-foreground">
                Files
              </span>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-8 w-8 shrink-0"
                onClick={onClose}
                aria-label="Close"
              >
                <X className="size-4" />
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-1 border-t border-sidebar-border px-2 py-1.5">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                className="fs-nav h-8 shrink-0 gap-1 px-2"
                disabled={!canGoUp || busy}
                onClick={() => setCurrentPath(parentDirectoryPath(currentPath))}
              >
                <ChevronLeft className="size-4" />
                Back
              </Button>
              <div className="fs-nav min-w-0 flex-1 truncate text-xs text-muted-foreground">
                {breadcrumbs.map((c, i) => (
                  <span key={`${c.path}-${i}`}>
                    {i > 0 ? ' / ' : null}
                    <button
                      type="button"
                      className="hover:text-foreground"
                      onClick={() => setCurrentPath(c.path)}
                    >
                      {c.label}
                    </button>
                  </span>
                ))}
              </div>
            </div>
          </div>

          <ScrollArea className="min-h-0 flex-1">
            <div className="flex flex-col gap-0.5 p-2 pb-4">
              {error && !loading ? (
                <div className="flex flex-col gap-2 px-1 py-2">
                  <p className="fs-nav text-destructive" role="alert">
                    {error}
                  </p>
                  <Button type="button" variant="secondary" size="sm" className="fs-nav w-fit" onClick={() => void load()}>
                    Retry
                  </Button>
                </div>
              ) : loading ? (
                <div className="flex items-center gap-2 px-1 py-2 text-muted-foreground">
                  <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
                  <span className="fs-nav text-sm">Loading…</span>
                </div>
              ) : reading ? (
                <div className="flex items-center gap-2 px-1 py-2 text-muted-foreground">
                  <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
                  <span className="fs-nav text-sm">Reading file…</span>
                </div>
              ) : items.length === 0 ? (
                <p className="fs-nav px-1 text-muted-foreground">Empty folder.</p>
              ) : (
                items.map((e) => (
                  <button
                    key={e.path}
                    type="button"
                    className={cn(
                      'fs-nav flex w-full items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-left font-medium outline-none ring-sidebar-ring',
                      'hover:border-sidebar-border hover:bg-sidebar-accent/30 focus-visible:ring-2',
                    )}
                    onClick={() => void onEntryClick(e)}
                  >
                    {e.type === 'dir' ? (
                      <Folder className="size-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <File className="size-4 shrink-0 text-muted-foreground opacity-70" />
                    )}
                    <span className="min-w-0 flex-1 truncate text-foreground">{e.name}</span>
                    {e.size != null && e.type === 'file' ? (
                      <span className="fs-nav shrink-0 text-xs text-muted-foreground">{e.size}</span>
                    ) : null}
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
        </aside>
      </div>
    </>
  )
}
