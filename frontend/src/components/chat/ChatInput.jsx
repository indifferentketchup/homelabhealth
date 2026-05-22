import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Plus, Search, SendHorizontal, Square, Upload, X } from 'lucide-react'

import { toggleWebSearch } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

// Read a File into a text-attachment shape, rejecting images outright and
// stripping any embedded null bytes (PG's TEXT type rejects 0x00, which
// previously caused 500s when a binary file got attached and the message
// INSERT blew up with `CharacterNotInRepertoireError`). Returns either
// { value: { filename, path, content } } or { error: string } for the
// caller to surface as a toast. Future: when we wire vision-capable
// models, image MIME types will get a separate base64-data-URL path.
async function loadFileAsTextAttachment(file) {
  if (!file) return { error: 'No file' }
  const type = (file.type || '').toLowerCase()
  if (type.startsWith('image/')) {
    return { error: `Can't attach images yet (${file.name}). Vision support is on the roadmap.` }
  }
  if (type.startsWith('video/') || type.startsWith('audio/')) {
    return { error: `Can't attach ${type.split('/')[0]} files (${file.name}).` }
  }
  let text
  try {
    text = await file.text()
  } catch {
    return { error: `Could not read ${file.name}.` }
  }
  if (text == null) return { error: `Could not read ${file.name}.` }
  // Defensive: strip any null bytes for non-image binaries that slip past
  // the MIME check (e.g., zip without a proper type, octet-stream).
  if (text.includes('\u0000')) {
    text = text.replace(/\u0000/g, '')
  }
  return {
    value: { filename: file.name, path: file.name, content: text },
  }
}

export function ChatInput({
  inputRef,
  value,
  onChange,
  onSend,
  disabled,
  streaming,
  onStop,
  activeChatId,
  chatMaxW,
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
  const [isDragOver, setIsDragOver] = useState(false)

  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const setWebSearchEnabled = useAppStore((s) => s.setWebSearchEnabled)

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

  // Local queue: messages typed while a previous response is streaming get
  // pushed here, then auto-fired when streaming transitions back to false.
  // Queue items are renderable so the user can edit (tap to pop back into
  // the input) or delete (X button) before they fire.
  const [queue, setQueue] = useState([])
  const wasStreamingRef = useRef(false)
  useEffect(() => {
    // Streaming just transitioned true → false. If something is queued and
    // we're not in a disabled state, dequeue and send the next one.
    // queueMicrotask defers the onSend so React commits state changes from
    // the parent's stream-end before we kick off the next request.
    if (
      wasStreamingRef.current
      && !streaming
      && !disabled
      && queue.length > 0
    ) {
      const next = queue[0]
      setQueue((q) => q.slice(1))
      queueMicrotask(() => {
        onSend(next.text, next.options)
      })
    }
    wasStreamingRef.current = streaming
  }, [streaming, disabled, onSend, queue])

  function handleSend() {
    if (disabled) return
    let composed
    if (attachedFiles.length > 0) {
      const blocks = attachedFiles
        .map((f) => `**\`${f.filename}\`**\n\`\`\`\n${f.content}\n\`\`\``)
        .join('\n\n')
      composed = blocks + (value.trim() ? '\n\n' + value.trim() : '')
      if (!composed.trim()) return
    } else {
      if (!value.trim()) return
      composed = value
    }
    const options = {}
    setAttachedFiles([])
    onChange('')
    if (streaming) {
      const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
      setQueue((q) => [...q, { id, text: composed, options }])
    } else {
      onSend(composed, options)
    }
  }

  // Tap a queued chip → pull it back to the input for editing. Any text the
  // user is currently drafting is moved to the front of the queue (in the
  // edited chip's slot) so nothing is lost. The dequeue effect won't fire
  // while streaming, so this is safe mid-stream.
  function editQueued(idx) {
    const item = queue[idx]
    if (!item) return
    const draft = value
    setQueue((q) => {
      const without = [...q.slice(0, idx), ...q.slice(idx + 1)]
      if (draft.trim()) {
        const draftItem = {
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          text: draft,
          options: {},
        }
        return [...without.slice(0, idx), draftItem, ...without.slice(idx)]
      }
      return without
    })
    onChange(item.text)
  }

  function removeQueued(idx) {
    setQueue((q) => q.filter((_, i) => i !== idx))
  }

  function onKeyDownTa(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Sendable when there's content. Streaming is fine — submit will queue.
  const canSend =
    (Boolean(value.trim()) || attachedFiles.length > 0) && !disabled

  const recalcMenuPos = useCallback(() => {
    const btn = plusBtnRef.current
    if (!btn) return
    const r = btn.getBoundingClientRect()
    setMenuPos({ bottom: window.innerHeight - r.top + 8, left: r.left })
  }, [])

  useEffect(() => {
    if (!plusOpen) return
    const onViewportChange = () => recalcMenuPos()
    const vv = window.visualViewport
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('scroll', onViewportChange, true)
    vv?.addEventListener('resize', onViewportChange)
    vv?.addEventListener('scroll', onViewportChange)
    return () => {
      window.removeEventListener('resize', onViewportChange)
      window.removeEventListener('scroll', onViewportChange, true)
      vv?.removeEventListener('resize', onViewportChange)
      vv?.removeEventListener('scroll', onViewportChange)
    }
  }, [plusOpen, recalcMenuPos])

  function openPlus() {
    recalcMenuPos()
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
        className="relative mx-auto w-full max-h-[40dvh] min-h-0 flex-shrink-0 flex flex-col overflow-hidden rounded-2xl border border-border bg-card px-4 pt-3 transition-colors focus-within:border-ring/60 focus-within:ring-2 focus-within:ring-ring/30"
        style={{
          maxWidth: chatMaxW ?? '100%',
          // Card's own bottom padding (was pb-1.5 = 6px). Drops to 0 when the
          // on-screen keyboard is up so the toolbar sits flush above the
          // keyboard with no residual gap.
          paddingBottom: 'max(0px, calc(0.375rem - var(--bc-keyboard-pad, 0px)))',
        }}
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
            const item = await loadFileAsTextAttachment(file)
            if (item.error) {
              setToastMsg(item.error)
              window.setTimeout(() => setToastMsg(null), 3000)
              continue
            }
            setAttachedFiles((prev) => {
              if (prev.find((f) => f.filename === file.name)) return prev
              return [...prev, item.value]
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
          <textarea
            ref={(el) => {
              taRef.current = el
              if (inputRef != null) inputRef.current = el
            }}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDownTa}
            placeholder="Message…"
            disabled={disabled}
            rows={1}
            className="fs-input max-h-[calc(40dvh-2.75rem)] min-h-12 w-full resize-none overflow-y-auto border-0 bg-transparent text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
          />
        </div>
        {queue.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pb-1.5 pt-0.5">
            {queue.map((q, idx) => (
              <span
                key={q.id}
                className="flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs"
                style={{
                  borderColor: 'color-mix(in srgb, var(--orange, #ff8c00) 50%, transparent)',
                  color: 'var(--text)',
                  background: 'var(--bg-card)',
                }}
                title="Queued — tap to edit, X to delete"
              >
                <button
                  type="button"
                  className="max-w-[220px] truncate text-left outline-none"
                  onClick={() => editQueued(idx)}
                  aria-label={`Edit queued message ${idx + 1}`}
                >
                  <span className="opacity-70 mr-1 tabular-nums">{idx + 1}.</span>
                  {q.text.replace(/\s+/g, ' ').trim().slice(0, 60)}
                </button>
                <button
                  type="button"
                  aria-label="Remove queued message"
                  className="ml-0.5 inline-flex size-4 items-center justify-center rounded opacity-70 outline-none transition-opacity hover:opacity-100"
                  onClick={() => removeQueued(idx)}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            ))}
          </div>
        )}
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
                  className="ml-0.5 inline-flex size-4 items-center justify-center rounded text-muted-foreground outline-none transition-colors hover:bg-destructive/15 hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setAttachedFiles((prev) => prev.filter((x) => x.path !== f.path))}
                >
                  <X className="size-3" aria-hidden />
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
            <>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 animate-pulse"
                title="Stop generating"
                onClick={onStop}
                aria-label="Stop"
              >
                <Square className="size-4" />
              </Button>
              {canSend ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="shrink-0"
                  onClick={handleSend}
                  title="Queue for after current response"
                  aria-label="Queue message"
                >
                  <SendHorizontal className="size-4" />
                </Button>
              ) : null}
            </>
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
            className="fixed z-[9999] w-64 min-w-[16rem] rounded-lg border border-border bg-popover p-2 text-popover-foreground shadow-xl outline-none"
            style={{
              bottom: menuPos.bottom,
              left: menuPos.left,
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
                  className={cn(
                    'relative inline-flex h-6 w-10 shrink-0 rounded-full border border-border transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    webSearchEnabled ? 'bg-primary' : 'bg-muted',
                  )}
                >
                  <span
                    className={cn(
                      'pointer-events-none block size-5 translate-x-0.5 rounded-full bg-background shadow transition-transform',
                      webSearchEnabled && 'translate-x-[1.15rem]',
                    )}
                  />
                </button>
              </div>
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
          const item = await loadFileAsTextAttachment(file)
          if (item.error) {
            setToastMsg(item.error)
            window.setTimeout(() => setToastMsg(null), 3000)
            return
          }
          setAttachedFiles((prev) => {
            if (prev.find((f) => f.filename === file.name)) return prev
            return [...prev, item.value]
          })
        }}
      />
    </>
  )
}
