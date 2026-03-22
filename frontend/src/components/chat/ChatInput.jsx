import { useEffect, useRef, useState } from 'react'
import { FileUp, Plus, Search, SendHorizontal, Square, UserCircle } from 'lucide-react'

import { patchChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

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

export function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
  streaming,
  onStop,
  activeChatId,
}) {
  const taRef = useRef(null)
  const plusWrapRef = useRef(null)
  const [plusOpen, setPlusOpen] = useState(false)
  const [toastMsg, setToastMsg] = useState(null)

  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const setWebSearchEnabled = useAppStore((s) => s.setWebSearchEnabled)
  const personaDisplayName = useAppStore((s) => s.personaDisplayName)

  useEffect(() => {
    if (!toastMsg) return
    const t = window.setTimeout(() => setToastMsg(null), 2200)
    return () => window.clearTimeout(t)
  }, [toastMsg])

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxPx = window.innerHeight * 0.33
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

  async function applyWebSearch(next) {
    setWebSearchEnabled(next)
    if (activeChatId) {
      try {
        await patchChat(activeChatId, { web_search_enabled: next })
      } catch {
        /* ignore */
      }
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!streaming && !disabled) onSend()
    }
  }

  return (
    <div className="bg-background p-3">
      {toastMsg && (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-[200] max-w-sm -translate-x-1/2 rounded-md border border-border bg-popover px-4 py-2 text-center text-sm text-popover-foreground shadow-md"
        >
          {toastMsg}
        </div>
      )}
      <div className="mx-auto flex w-full items-end gap-2">
        <div ref={plusWrapRef} className="relative shrink-0">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="shrink-0 border-border"
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
                <div className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5">
                  <span className="flex items-center gap-2 text-sm text-foreground">
                    <Search className="size-4 text-muted-foreground" />
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
                <button
                  type="button"
                  role="menuitem"
                  className="flex h-9 w-full cursor-default items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                  disabled
                >
                  <UserCircle className="size-4 text-muted-foreground" />
                  <span className="truncate">Persona: {personaDisplayName}</span>
                </button>
              </div>
            </div>
          )}
        </div>

        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message…"
          disabled={disabled || streaming}
          rows={1}
          className="min-h-[2.75rem] flex-1 resize-none rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground outline-none ring-ring placeholder:text-muted-foreground focus-visible:ring-2"
        />

        {streaming ? (
          <Button type="button" variant="secondary" size="icon" className="shrink-0" onClick={onStop} aria-label="Stop">
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            type="button"
            size="icon"
            className="shrink-0"
            onClick={onSend}
            disabled={disabled || !value.trim()}
            aria-label="Send"
          >
            <SendHorizontal className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
