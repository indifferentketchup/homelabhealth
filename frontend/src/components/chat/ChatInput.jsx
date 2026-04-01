import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { FolderOpen, Plus, Search, SendHorizontal, Square, Upload } from 'lucide-react'

import { dubdriveLs, dubdriveRead } from '@/api/dubdrive.js'
import { toggleWebSearch } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

import { FileBrowserPanel } from './FileBrowserPanel.jsx'
import { PersonaGlyph } from './PersonaGlyph.jsx'

export function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
  streaming,
  onStop,
  activeChatId,
  chatMaxW,
  hidePersonaInMenu = false,
  dawSyncFolder,
}) {
  const taRef = useRef(null)
  const uploadInputRef = useRef(null)
  const plusWrapRef = useRef(null)
  const plusBtnRef = useRef(null)
  const plusMenuRef = useRef(null)
  const [menuPos, setMenuPos] = useState({ bottom: 0, left: 0 })
  const [plusOpen, setPlusOpen] = useState(false)
  const [toastMsg, setToastMsg] = useState(null)

  const [attachedFiles, setAttachedFiles] = useState([])
  const [atQuery, setAtQuery] = useState(null)
  const [atResults, setAtResults] = useState([])
  const [atLoading, setAtLoading] = useState(false)
  const [atIndex, setAtIndex] = useState(0)
  const [fileBrowserOpen, setFileBrowserOpen] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)

  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const setWebSearchEnabled = useAppStore((s) => s.setWebSearchEnabled)
  const personaDisplayName = useAppStore((s) => s.personaDisplayName)
  const personaIconUrl = useAppStore((s) => s.personaIconUrl)
  const personaEmoji = useAppStore((s) => s.personaEmoji)

  const q = (atQuery || '').toLowerCase()
  const filtered =
    atQuery !== null
      ? atResults.filter((item) => item.name.toLowerCase().includes(q)).slice(0, 8)
      : []

  useEffect(() => {
    if (!toastMsg) return
    const t = window.setTimeout(() => setToastMsg(null), 2200)
    return () => window.clearTimeout(t)
  }, [toastMsg])

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxPx = window.innerHeight * 0.4
    el.style.height = `${Math.min(el.scrollHeight, maxPx)}px`
  }, [value])

  useEffect(() => {
    if (!plusOpen) return
    function onMouseDown(e) {
      if (
        plusWrapRef.current &&
        !plusWrapRef.current.contains(e.target) &&
        plusMenuRef.current &&
        !plusMenuRef.current.contains(e.target)
      ) {
        setPlusOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [plusOpen])

  useEffect(() => {
    if (!plusOpen) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setPlusOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [plusOpen])

  async function applyWebSearch(next) {
    const prev = webSearchEnabled
    setWebSearchEnabled(next)
    if (activeChatId) {
      try {
        const res = await toggleWebSearch(activeChatId, next)
        if (res?.web_search_enabled != null) setWebSearchEnabled(Boolean(res.web_search_enabled))
      } catch {
        setWebSearchEnabled(prev)
      }
    }
  }

  function handleSend() {
    if (streaming || disabled) return
    if (attachedFiles.length > 0) {
      const blocks = attachedFiles
        .map((f) => `**\`${f.filename}\`**\n\`\`\`\n${f.content}\n\`\`\``)
        .join('\n\n')
      const composed = blocks + (value.trim() ? '\n\n' + value.trim() : '')
      if (!composed.trim()) return
      setAttachedFiles([])
      onChange('')
      onSend(composed)
    } else {
      if (!value.trim()) return
      onSend()
    }
  }

  async function selectAtFile(item) {
    setAtQuery(null)
    setAtResults([])
    const newVal = value.replace(/(?:^|\s)@\S*$/, (m) => (m.startsWith('@') ? '' : m[0]))
    onChange(newVal.trimEnd())
    try {
      const content = await dubdriveRead(item.path)
      setAttachedFiles((prev) => {
        if (prev.find((f) => f.path === item.path)) return prev
        return [...prev, { filename: item.name, path: item.path, content }]
      })
    } catch {
      /* silently fail — file just won't be attached */
    }
  }

  function onKeyDownTa(e) {
    if (atQuery !== null) {
      const flen = filtered.length
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setAtIndex((i) => Math.min(i + 1, Math.max(0, flen - 1)))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setAtIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        if (filtered[atIndex]) void selectAtFile(filtered[atIndex])
        return
      }
      if (e.key === 'Escape') {
        setAtQuery(null)
        setAtResults([])
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend =
    (Boolean(value.trim()) || attachedFiles.length > 0) && !streaming && !disabled

  function openPlus() {
    if (plusBtnRef.current) {
      const r = plusBtnRef.current.getBoundingClientRect()
      setMenuPos({ bottom: window.innerHeight - r.top + 8, left: r.left })
    }
    setPlusOpen((o) => !o)
  }

  return (
    <>
      {toastMsg && (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-[200] max-w-sm -translate-x-1/2 rounded-md border border-border bg-popover px-4 py-2 text-center text-sm text-popover-foreground shadow-md"
        >
          {toastMsg}
        </div>
      )}
      <div
        className="relative mx-auto w-full max-h-[40vh] min-h-0 flex-shrink-0 flex flex-col overflow-hidden rounded-2xl border border-border bg-card px-4 pb-1.5 pt-3"
        style={{ maxWidth: chatMaxW ?? '100%' }}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) setIsDragOver(false)
        }}
        onDrop={async (e) => {
          e.preventDefault()
          setIsDragOver(false)
          const files = Array.from(e.dataTransfer.files)
          for (const file of files) {
            const text = await file.text().catch(() => null)
            if (text === null) continue
            setAttachedFiles((prev) => {
              if (prev.find((f) => f.filename === file.name)) return prev
              return [...prev, { filename: file.name, path: file.name, content: text }]
            })
          }
        }}
      >
        {isDragOver && (
          <div className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-primary/10">
            <span className="text-sm font-medium text-primary">Drop files to attach</span>
          </div>
        )}
        <div className="relative min-h-0">
          {atQuery !== null && (
            <div className="absolute bottom-full left-0 z-50 mb-2 w-72 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
              {atLoading && <div className="px-3 py-2 text-sm text-muted-foreground">Loading…</div>}
              {!atLoading && filtered.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">No files found</div>
              )}
              {!atLoading &&
                filtered.map((item, i) => (
                  <button
                    key={item.path}
                    type="button"
                    className={cn(
                      'flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-accent',
                      i === atIndex && 'bg-accent text-accent-foreground',
                    )}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      void selectAtFile(item)
                    }}
                  >
                    <span className="truncate">{item.name}</span>
                    <span className="ml-auto max-w-[120px] truncate text-xs text-muted-foreground">
                      {item.path}
                    </span>
                  </button>
                ))}
            </div>
          )}
          <textarea
            ref={taRef}
            value={value}
            onChange={(e) => {
              const val = e.target.value
              onChange(val)
              const match = val.match(/(?:^|\s)@(\S*)$/)
              if (match) {
                const qq = match[1]
                setAtQuery(qq)
                setAtIndex(0)
                setAtLoading(true)
                dubdriveLs((dawSyncFolder && String(dawSyncFolder).trim()) || '/HomeLabRepos')
                  .then((data) => {
                    const files = (data?.items || []).filter(
                      (i) => (i?.type || '').toLowerCase() === 'file',
                    )
                    setAtResults(files)
                    setAtLoading(false)
                  })
                  .catch(() => {
                    setAtResults([])
                    setAtLoading(false)
                  })
              } else {
                setAtQuery(null)
                setAtResults([])
              }
            }}
            onKeyDown={onKeyDownTa}
            placeholder="Message…"
            disabled={disabled || streaming}
            rows={3}
            className="fs-input max-h-[calc(40vh-2.75rem)] min-h-12 w-full resize-none overflow-y-auto border-0 bg-transparent text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
          />
        </div>
        {attachedFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pb-1.5 pt-0.5">
            {attachedFiles.map((f) => (
              <span
                key={f.path}
                className="flex items-center gap-1 rounded-md border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                <span className="max-w-[180px] truncate">{f.filename}</span>
                <button
                  type="button"
                  aria-label={`Remove ${f.filename}`}
                  className="ml-0.5 hover:text-foreground"
                  onClick={() => setAttachedFiles((prev) => prev.filter((x) => x.path !== f.path))}
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex shrink-0 items-center justify-between">
          <div ref={plusWrapRef} className="relative shrink-0">
            <span ref={plusBtnRef} className="inline-flex shrink-0">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                aria-label="More actions"
                aria-expanded={plusOpen}
                aria-haspopup="menu"
                onClick={openPlus}
              >
                <Plus className="size-4" />
              </Button>
            </span>
          </div>

          {streaming ? (
            <Button type="button" variant="ghost" size="icon" className="shrink-0" onClick={onStop} aria-label="Stop">
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              onClick={handleSend}
              disabled={disabled || !canSend}
              aria-label="Send"
            >
              <SendHorizontal className="size-4" />
            </Button>
          )}
        </div>
      </div>
      {plusOpen &&
        createPortal(
          <div
            ref={plusMenuRef}
            className="w-64 p-2 text-popover-foreground outline-none"
            style={{
              position: 'fixed',
              bottom: menuPos.bottom,
              left: menuPos.left,
              zIndex: 9999,
              minWidth: 256,
              background: 'var(--popover)',
              border: '1px solid var(--border)',
              borderRadius: 8,
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            }}
            role="menu"
            aria-label="More actions"
          >
            <div className="flex flex-col gap-1">
              <button
                type="button"
                role="menuitem"
                className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  setPlusOpen(false)
                  uploadInputRef.current?.click()
                }}
              >
                <Upload className="size-4 shrink-0 opacity-70" />
                Upload file
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  setFileBrowserOpen(true)
                  setPlusOpen(false)
                }}
              >
                <FolderOpen className="size-4 text-muted-foreground" />
                Browse files
              </button>
              <div
                className={cn(
                  'flex items-center justify-between gap-2 rounded-md px-2 py-1.5',
                  webSearchEnabled && 'bg-accent text-accent-foreground',
                )}
              >
                <span className="flex items-center gap-2 text-sm">
                  <Search
                    className={cn(
                      'size-4',
                      webSearchEnabled ? 'text-accent-foreground' : 'text-muted-foreground',
                    )}
                  />
                  Web search
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={webSearchEnabled}
                  onClick={() => applyWebSearch(!webSearchEnabled)}
                  className="relative inline-flex h-6 w-10 shrink-0 rounded-full border border-border transition-colors"
                  style={{
                    backgroundColor: webSearchEnabled ? 'var(--primary)' : 'var(--muted)',
                  }}
                >
                  <span
                    className={cn(
                      'pointer-events-none block size-5 translate-x-0.5 rounded-full shadow transition-transform',
                      webSearchEnabled && 'translate-x-[1.15rem]',
                    )}
                    style={{ backgroundColor: 'var(--background)' }}
                  />
                </button>
              </div>
              {!hidePersonaInMenu && (
                <button
                  type="button"
                  role="menuitem"
                  className="flex h-9 w-full cursor-default items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                  disabled
                >
                  <PersonaGlyph
                    kind="menu"
                    iconUrl={personaIconUrl}
                    emoji={personaEmoji}
                    className="text-muted-foreground"
                  />
                  <span className="truncate">Persona: {personaDisplayName}</span>
                </button>
              )}
            </div>
          </div>,
          document.body,
        )}
      <input
        ref={uploadInputRef}
        type="file"
        className="hidden"
        onChange={async (e) => {
          const file = e.target.files?.[0]
          if (!file) return
          e.target.value = ''
          const text = await file.text().catch(() => null)
          if (text == null) {
            setToastMsg('Could not read file')
            setTimeout(() => setToastMsg(null), 3000)
            return
          }
          setAttachedFiles((prev) => {
            if (prev.find((f) => f.filename === file.name)) return prev
            return [...prev, { filename: file.name, path: file.name, content: text }]
          })
        }}
      />
      <FileBrowserPanel
        isOpen={fileBrowserOpen}
        onClose={() => setFileBrowserOpen(false)}
        rootPath={dawSyncFolder || undefined}
        onFileSelect={async (filename, path, content) => {
          setAttachedFiles((prev) => {
            if (prev.find((f) => f.path === path)) return prev
            return [...prev, { filename, path, content }]
          })
          setFileBrowserOpen(false)
        }}
      />
    </>
  )
}
