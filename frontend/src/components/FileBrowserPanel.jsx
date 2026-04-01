import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronLeft, File, Folder, X } from 'lucide-react'

import { dubdriveLs, dubdriveRead } from '@/api/index.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'
import {
  DUBDRIVE_HOMELAB_ROOT,
  normalizeDubdriveLsPayload,
  parentDirectoryPath,
} from '@/lib/dubdriveEntries.js'

function basenameOnly(path) {
  const s = (path || '').replace(/\/+$/, '')
  if (!s) return path || ''
  return s.split('/').pop() || s
}

export function FileBrowserPanel({ isOpen, onClose, onFileSelect }) {
  const root = DUBDRIVE_HOMELAB_ROOT
  const [currentPath, setCurrentPath] = useState(root)
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [readingOpen, setReadingOpen] = useState(false)

  useEffect(() => {
    if (!isOpen) return
    setCurrentPath(root)
  }, [isOpen, root])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await dubdriveLs(currentPath)
      setEntries(normalizeDubdriveLsPayload(data, currentPath))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setEntries([])
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
    if (entry.isDir) {
      setCurrentPath(entry.path.endsWith('/') ? entry.path : `${entry.path}/`)
      return
    }
    setReadingOpen(true)
    setError(null)
    try {
      const content = await dubdriveRead(entry.path)
      const text =
        typeof content === 'string' ? content : JSON.stringify(content, null, 2)
      onFileSelect?.(basenameOnly(entry.path), text)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setReadingOpen(false)
    }
  }

  if (!isOpen) return null

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
            <div className="flex min-h-14 w-full items-center justify-between gap-2 px-2 py-2">
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
                disabled={!canGoUp || loading || readingOpen}
                onClick={() => setCurrentPath(parentDirectoryPath(currentPath))}
              >
                <ChevronLeft className="size-4" />
                Up
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
              {error ? (
                <p className="fs-nav px-1 text-destructive" role="alert">
                  {error}
                </p>
              ) : loading || readingOpen ? (
                <p className="fs-nav px-1 text-muted-foreground">Loading…</p>
              ) : entries.length === 0 ? (
                <p className="fs-nav px-1 text-muted-foreground">Empty folder.</p>
              ) : (
                entries.map((e) => (
                  <button
                    key={e.path}
                    type="button"
                    className={cn(
                      'fs-nav flex w-full items-center gap-2 rounded-md border border-transparent px-2 py-1.5 text-left font-medium outline-none ring-sidebar-ring',
                      'hover:border-sidebar-border hover:bg-sidebar-accent/30 focus-visible:ring-2',
                    )}
                    onClick={() => void onEntryClick(e)}
                  >
                    {e.isDir ? (
                      <Folder className="size-4 shrink-0 text-muted-foreground" />
                    ) : (
                      <File className="size-4 shrink-0 text-muted-foreground opacity-70" />
                    )}
                    <span className="min-w-0 truncate text-foreground">{e.name}</span>
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
