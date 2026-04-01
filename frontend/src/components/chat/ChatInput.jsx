import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { FileUp, Plus, Search, SendHorizontal, Square, X } from 'lucide-react'

import { dubdriveLs, dubdriveRead } from '@/api/index.js'
import { toggleWebSearch } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { collectAllFilesUnder, DUBDRIVE_HOMELAB_ROOT, fuzzyMatchFilename, getActiveMention } from '@/lib/dubdriveEntries.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

import { PersonaGlyph } from './PersonaGlyph.jsx'

const PLUS_MENU_PANEL_STYLE = {
  position: 'absolute',
  bottom: '100%',
  left: 0,
  marginBottom: 8,
  zIndex: 9999,
  minWidth: 256,
  background: 'var(--bg-panel)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
}

function getCaretViewportPoint(textarea, position) {
  const style = window.getComputedStyle(textarea)
  const div = document.createElement('div')
  const props = [
    'fontFamily',
    'fontSize',
    'fontWeight',
    'fontStyle',
    'letterSpacing',
    'textTransform',
    'wordSpacing',
    'textIndent',
    'whiteSpace',
    'overflowWrap',
    'width',
    'paddingTop',
    'paddingRight',
    'paddingBottom',
    'paddingLeft',
    'borderTopWidth',
    'borderRightWidth',
    'borderBottomWidth',
    'borderLeftWidth',
    'boxSizing',
    'lineHeight',
  ]
  for (const p of props) {
    div.style[p] = style[p]
  }
  div.style.position = 'absolute'
  div.style.visibility = 'hidden'
  div.style.whiteSpace = 'pre-wrap'
  div.style.wordWrap = 'break-word'
  div.style.overflow = 'hidden'
  div.style.width = `${textarea.clientWidth}px`
  div.textContent = textarea.value.slice(0, position)
  const marker = document.createElement('span')
  marker.textContent = textarea.value.slice(position, position + 1) || '.'
  div.appendChild(marker)
  document.body.appendChild(div)
  const y = marker.offsetTop
  const x = marker.offsetLeft
  document.body.removeChild(div)
  const ta = textarea.getBoundingClientRect()
  const lh = parseFloat(style.lineHeight) || 20
  return {
    top: ta.top + y - textarea.scrollTop,
    left: ta.left + x - textarea.scrollLeft,
    lineHeight: lh,
  }
}

function formatAttachedBlock(filename, content) {
  const body = typeof content === 'string' ? content : JSON.stringify(content, null, 2)
  return `**\`${filename}\`**\n\`\`\`\n${body}\n\`\`\``
}

function composeOutgoingMessage(userText, files) {
  const t = userText.trim()
  const blocks = (files || []).map((f) => formatAttachedBlock(f.filename, f.content))
  if (blocks.length === 0) return t
  if (!t) return blocks.join('\n\n')
  return `${blocks.join('\n\n')}\n\n${t}`
}

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
}) {
  const taRef = useRef(null)
  const caretRef = useRef(0)
  const plusWrapRef = useRef(null)
  const pickRef = useRef(null)
  const [plusOpen, setPlusOpen] = useState(false)
  const [toastMsg, setToastMsg] = useState(null)
  const [caretBump, setCaretBump] = useState(0)
  const [attachedFiles, setAttachedFiles] = useState([])
  const [flatFiles, setFlatFiles] = useState([])
  const [flatErr, setFlatErr] = useState(null)
  const [flatLoading, setFlatLoading] = useState(false)
  const [pickPos, setPickPos] = useState(null)
  const flatLoadingRef = useRef(false)
  const mentionWasActiveRef = useRef(false)

  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const setWebSearchEnabled = useAppStore((s) => s.setWebSearchEnabled)
  const personaDisplayName = useAppStore((s) => s.personaDisplayName)
  const personaIconUrl = useAppStore((s) => s.personaIconUrl)
  const personaEmoji = useAppStore((s) => s.personaEmoji)

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
      if (plusWrapRef.current && !plusWrapRef.current.contains(e.target)) {
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

  function bumpCaret() {
    const el = taRef.current
    if (el) caretRef.current = el.selectionStart ?? 0
    setCaretBump((n) => n + 1)
  }

  useEffect(() => {
    const caret = caretRef.current ?? value.length
    const m = getActiveMention(value, caret)
    if (!m) {
      mentionWasActiveRef.current = false
      flatLoadingRef.current = false
      setFlatLoading(false)
      return
    }
    if (!mentionWasActiveRef.current) {
      flatLoadingRef.current = false
    }
    mentionWasActiveRef.current = true
    if (flatLoadingRef.current) return
    flatLoadingRef.current = true
    setFlatErr(null)
    setFlatLoading(true)
    void (async () => {
      try {
        const files = await collectAllFilesUnder(DUBDRIVE_HOMELAB_ROOT, dubdriveLs)
        setFlatFiles(files.filter((f) => !f.isDir))
      } catch (e) {
        setFlatErr(e instanceof Error ? e.message : String(e))
        flatLoadingRef.current = false
      } finally {
        setFlatLoading(false)
      }
    })()
  }, [value, caretBump])

  useLayoutEffect(() => {
    const el = taRef.current
    const caret = caretRef.current ?? value.length
    const m = getActiveMention(value, caret)
    if (!m || !el) {
      setPickPos(null)
      return
    }
    setPickPos(getCaretViewportPoint(el, caret))
  }, [value, caretBump])

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

  function submitComposed() {
    const composed = composeOutgoingMessage(value, attachedFiles)
    if (!composed.trim() || streaming || disabled) return
    flushSync(() => {
      onChange(composed.trim())
      setAttachedFiles([])
    })
    onSend()
  }

  function onKeyDownTa(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submitComposed()
    }
  }

  async function onPickFile(entry) {
    const el = taRef.current
    const caret = el?.selectionStart ?? value.length
    const m = getActiveMention(value, caret)
    if (!m) return
    try {
      const raw = await dubdriveRead(entry.path)
      const text = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2)
      const next = value.slice(0, m.start) + value.slice(caret)
      onChange(next)
      setAttachedFiles((prev) => [...prev, { filename: entry.name, content: text }])
      requestAnimationFrame(() => {
        if (el) {
          const pos = m.start
          el.focus()
          el.setSelectionRange(pos, pos)
          caretRef.current = pos
        }
      })
    } catch (err) {
      setToastMsg(err instanceof Error ? err.message : 'Could not read file')
    }
  }

  const caretNow = caretRef.current ?? value.length
  const activeMention = getActiveMention(value, caretNow)
  const pickFiltered =
    activeMention && !flatErr
      ? flatFiles.filter((f) => fuzzyMatchFilename(f.name, activeMention.query)).slice(0, 100)
      : []
  const outgoingPreview = composeOutgoingMessage(value, attachedFiles)
  const canSend = Boolean(outgoingPreview.trim()) && !streaming && !disabled

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
      {pickPos && activeMention ? (
        <div
          ref={pickRef}
          className="p-1 text-popover-foreground outline-none"
          role="listbox"
          aria-label="Attach file from DubDrive"
          style={{
            position: 'fixed',
            top: `${pickPos.top + pickPos.lineHeight}px`,
            left: `${pickPos.left}px`,
            zIndex: 10000,
            minWidth: 220,
            maxWidth: 'min(90vw, 360px)',
            maxHeight: 240,
            overflowY: 'auto',
            background: 'var(--bg-panel)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
          }}
        >
          {flatErr ? (
            <p className="px-2 py-1.5 text-sm text-destructive" role="alert">
              {flatErr}
            </p>
          ) : flatLoading ? (
            <p className="px-2 py-1.5 text-sm text-muted-foreground">Loading files…</p>
          ) : pickFiltered.length === 0 ? (
            <p className="px-2 py-1.5 text-sm text-muted-foreground">No matches</p>
          ) : (
            <ul className="flex flex-col gap-0.5 py-0.5">
              {pickFiltered.map((f) => (
                <li key={f.path}>
                  <button
                    type="button"
                    role="option"
                    className="flex w-full truncate rounded-md px-2 py-1.5 text-left text-sm text-foreground hover:bg-accent hover:text-accent-foreground"
                    onClick={() => void onPickFile(f)}
                  >
                    {f.name}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
      <div
        className="mx-auto w-full max-h-[40vh] min-h-0 flex-shrink-0 flex flex-col overflow-hidden rounded-2xl border border-border bg-card px-4 pb-1.5 pt-3"
        style={{ maxWidth: chatMaxW ?? '100%' }}
      >
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => {
            caretRef.current = e.target.selectionStart ?? 0
            onChange(e.target.value)
          }}
          onSelect={bumpCaret}
          onClick={bumpCaret}
          onKeyUp={bumpCaret}
          onKeyDown={onKeyDownTa}
          placeholder="Message…"
          disabled={disabled || streaming}
          rows={3}
          className="fs-input max-h-[calc(40vh-2.75rem)] min-h-12 w-full resize-none overflow-y-auto border-0 bg-transparent text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
        />
        {attachedFiles.length > 0 ? (
          <div className="flex flex-wrap gap-1.5 pb-2 pt-0.5">
            {attachedFiles.map((f, i) => (
              <span
                key={`${f.filename}-${i}`}
                className="inline-flex max-w-[min(100%,14rem)] items-center gap-1 rounded-full border border-border bg-muted/50 px-2 py-0.5 text-xs text-foreground"
              >
                <span className="truncate">{f.filename}</span>
                <button
                  type="button"
                  className="shrink-0 rounded-full p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground"
                  aria-label={`Remove ${f.filename}`}
                  onClick={() => setAttachedFiles((prev) => prev.filter((_, j) => j !== i))}
                >
                  <X className="size-3.5" />
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <div className="flex shrink-0 items-center justify-between">
          <div ref={plusWrapRef} className="relative shrink-0">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              aria-label="More actions"
              aria-expanded={plusOpen}
              aria-haspopup="menu"
              onClick={() => setPlusOpen((o) => !o)}
            >
              <Plus className="size-4" />
            </Button>
            {plusOpen && (
              <div
                className="w-64 p-2 text-popover-foreground outline-none"
                style={PLUS_MENU_PANEL_STYLE}
                role="menu"
                aria-label="More actions"
              >
                <div className="flex flex-col gap-1">
                  <button
                    type="button"
                    role="menuitem"
                    className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                    onClick={() => {
                      setToastMsg('Coming soon')
                      setPlusOpen(false)
                    }}
                  >
                    <FileUp className="size-4 text-muted-foreground" />
                    Upload files
                  </button>
                  <div
                    className={cn(
                      'flex items-center justify-between gap-2 rounded-md px-2 py-1.5',
                      webSearchEnabled && 'bg-accent text-accent-foreground',
                    )}
                  >
                    <span className="flex items-center gap-2 text-sm">
                      <Search className={cn('size-4', webSearchEnabled ? 'text-accent-foreground' : 'text-muted-foreground')} />
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
              </div>
            )}
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
              onClick={submitComposed}
              disabled={disabled || !canSend}
              aria-label="Send"
            >
              <SendHorizontal className="size-4" />
            </Button>
          )}
        </div>
      </div>
    </>
  )
}
