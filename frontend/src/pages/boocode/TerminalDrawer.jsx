import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronUp, Plus, TerminalSquare } from 'lucide-react'

import * as terminalsApi from '@/api/terminals.js'
import { Button } from '@/components/ui/button'

import TerminalPane from './TerminalPane.jsx'

const DEFAULT_HEIGHT = 320
const MIN_HEIGHT = 120
const MAX_HEIGHT_VH = 0.8
const COLLAPSED_HEIGHT = 36
const POLL_MS = 15_000

const storageKey = (dawId) => `boocode:terminal-drawer:${dawId ?? 'unscoped'}`

function readPersisted(dawId) {
  if (typeof window === 'undefined') return { open: false, height: DEFAULT_HEIGHT }
  try {
    const raw = window.localStorage.getItem(storageKey(dawId))
    if (!raw) return { open: false, height: DEFAULT_HEIGHT }
    const parsed = JSON.parse(raw)
    const h = Number(parsed?.height)
    return {
      open: Boolean(parsed?.open),
      height: Number.isFinite(h) && h >= MIN_HEIGHT ? h : DEFAULT_HEIGHT,
    }
  } catch {
    return { open: false, height: DEFAULT_HEIGHT }
  }
}

function writePersisted(dawId, value) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(storageKey(dawId), JSON.stringify(value))
  } catch {
    /* non-fatal */
  }
}

// Commit 2 slice: drawer shell, drag-resize, per-DAW persistence, Ctrl+`
// toggle, session list + live pane. Tab chrome, context menu, and the
// NewTerminalModal land in commit 3 — the `+` button here just fires the
// `boocode:new-terminal` event so the wiring is ready.
export default function TerminalDrawer({ dawId }) {
  const qc = useQueryClient()
  const [{ open, height }, setDrawerState] = useState(() => readPersisted(dawId))
  const [pinnedActiveId, setPinnedActiveId] = useState(null)
  const [toastMsg, setToastMsg] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [lastDaw, setLastDaw] = useState(dawId)
  const dragRef = useRef({ startY: 0, startHeight: 0 })

  // Adjust state when dawId changes — reloads persisted height/open and drops
  // the active tab (React docs: "Adjusting some state when a prop changes").
  if (dawId !== lastDaw) {
    setLastDaw(dawId)
    setDrawerState(readPersisted(dawId))
    setPinnedActiveId(null)
  }

  useEffect(() => {
    writePersisted(dawId, { open, height })
  }, [dawId, open, height])

  useEffect(() => {
    if (!toastMsg) return
    const t = window.setTimeout(() => setToastMsg(null), 2500)
    return () => window.clearTimeout(t)
  }, [toastMsg])

  const { data } = useQuery({
    queryKey: ['terminals', dawId ?? null],
    queryFn: () => terminalsApi.list({ dawId }),
    staleTime: 5_000,
    refetchInterval: POLL_MS,
  })

  const sessions = useMemo(() => {
    const rows = Array.isArray(data?.active) ? data.active : []
    return rows.slice().sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return (a.created_at || '').localeCompare(b.created_at || '')
    })
  }, [data])

  // Effective active tab: explicit pin if still in the list, else first tab.
  const activeSessionId = useMemo(() => {
    if (sessions.length === 0) return null
    if (pinnedActiveId && sessions.some((s) => s.id === pinnedActiveId)) {
      return pinnedActiveId
    }
    return sessions[0].id
  }, [sessions, pinnedActiveId])

  const setActiveSessionId = useCallback((id) => {
    setPinnedActiveId(id)
  }, [])

  const invalidateSessions = useCallback(
    () => qc.invalidateQueries({ queryKey: ['terminals', dawId ?? null] }),
    [qc, dawId],
  )

  const setOpen = useCallback((next) => {
    setDrawerState((prev) => ({ ...prev, open: next }))
  }, [])

  const toggle = useCallback(() => {
    setDrawerState((prev) => ({ ...prev, open: !prev.open }))
  }, [])

  const handleDragStart = useCallback(
    (e) => {
      e.preventDefault()
      const clientY = e.touches ? e.touches[0].clientY : e.clientY
      dragRef.current = { startY: clientY, startHeight: height }
      setDragging(true)
    },
    [height],
  )

  useEffect(() => {
    if (!dragging) return
    function onMove(e) {
      const st = dragRef.current
      const clientY = e.touches ? e.touches[0].clientY : e.clientY
      const dy = st.startY - clientY
      const maxPx = Math.max(MIN_HEIGHT, Math.floor(window.innerHeight * MAX_HEIGHT_VH))
      const next = Math.max(MIN_HEIGHT, Math.min(maxPx, st.startHeight + dy))
      setDrawerState((prev) => ({ ...prev, height: next }))
    }
    function onUp() {
      setDragging(false)
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('touchmove', onMove, { passive: false })
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchend', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('touchmove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchend', onUp)
    }
  }, [dragging])

  useEffect(() => {
    function onKey(e) {
      if (!e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key !== '`') return
      const target = e.target
      if (
        target &&
        target.tagName !== 'BODY' &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return
      }
      e.preventDefault()
      toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle])

  useEffect(() => {
    function onNew() {
      setOpen(true)
    }
    function onOpen(e) {
      const detail = e.detail || {}
      if (!detail.sessionId) return
      setActiveSessionId(detail.sessionId)
      setOpen(true)
    }
    function onSend(e) {
      const { sessionId, text, appendNewline } = e.detail || {}
      if (!sessionId || typeof text !== 'string') return
      ;(async () => {
        try {
          await terminalsApi.paste(sessionId, text, Boolean(appendNewline))
          setToastMsg('Sent to terminal')
        } catch (err) {
          setToastMsg(err?.message || 'Paste failed')
        }
      })()
    }
    window.addEventListener('boocode:new-terminal', onNew)
    window.addEventListener('boocode:open-terminal', onOpen)
    window.addEventListener('boocode:send-to-terminal', onSend)
    return () => {
      window.removeEventListener('boocode:new-terminal', onNew)
      window.removeEventListener('boocode:open-terminal', onOpen)
      window.removeEventListener('boocode:send-to-terminal', onSend)
    }
  }, [setOpen, setActiveSessionId])

  const handleEvicted = useCallback(async () => {
    await invalidateSessions()
  }, [invalidateSessions])

  const handleNewClick = useCallback(() => {
    setOpen(true)
    window.dispatchEvent(
      new CustomEvent('boocode:new-terminal', { detail: { dawId } }),
    )
  }, [dawId, setOpen])

  const renderHeight = open ? height : COLLAPSED_HEIGHT

  return (
    <>
      <div
        className="boocode-terminal-drawer flex flex-col overflow-hidden border-t"
        style={{
          height: `${renderHeight}px`,
          borderColor: 'var(--border)',
          background: 'var(--bg-panel)',
          transition: dragging ? 'none' : 'height 120ms ease-out',
        }}
        aria-label="Terminals drawer"
      >
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize terminal drawer"
          tabIndex={-1}
          className="group relative flex h-2 cursor-row-resize select-none items-center justify-center"
          onMouseDown={open ? handleDragStart : undefined}
          onTouchStart={open ? handleDragStart : undefined}
          style={{ background: 'transparent' }}
        >
          <div
            className="h-[3px] w-12 rounded-full opacity-50 transition-opacity group-hover:opacity-100"
            style={{ background: 'var(--orange, #ff8c00)' }}
          />
        </div>

        {!open ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="flex h-full w-full items-center gap-2 px-3 text-left text-xs"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              color: 'var(--text)',
            }}
            aria-label="Open terminal drawer"
          >
            <TerminalSquare className="size-4" style={{ color: 'var(--orange, #ff8c00)' }} />
            <span className="uppercase tracking-[0.2em]">Terminals</span>
            {sessions.length > 0 ? (
              <span className="opacity-70">({sessions.length})</span>
            ) : null}
            <ChevronUp className="ml-auto size-4 opacity-70" />
          </button>
        ) : (
          <>
            {/* Stub tab row — full TerminalTabBar lands in commit 3. */}
            <div
              className="flex min-h-0 items-center gap-1 border-b px-2 py-1 text-xs"
              style={{
                borderColor: 'var(--border)',
                background: 'var(--bg-card)',
                fontFamily: "'JetBrains Mono', monospace",
              }}
            >
              <TerminalSquare className="size-3.5" style={{ color: 'var(--orange, #ff8c00)' }} />
              <div className="flex min-w-0 flex-1 gap-1 overflow-x-auto">
                {sessions.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => setActiveSessionId(s.id)}
                    className="flex shrink-0 items-center gap-1 rounded border px-2 py-0.5"
                    style={{
                      borderColor:
                        s.id === activeSessionId ? 'var(--orange, #ff8c00)' : 'var(--border)',
                      color: s.id === activeSessionId ? 'var(--orange, #ff8c00)' : 'var(--text)',
                    }}
                  >
                    <span className="max-w-[14ch] truncate">
                      {s.label || s.machine_name || 'session'}
                    </span>
                  </button>
                ))}
              </div>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="New terminal"
                onClick={handleNewClick}
              >
                <Plus className="size-3.5" />
              </Button>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-label="Collapse terminal drawer"
                onClick={() => setOpen(false)}
              >
                <ChevronDown className="size-3.5" />
              </Button>
            </div>
            <div className="relative flex min-h-0 flex-1 overflow-hidden">
              {sessions.length === 0 ? (
                <div
                  className="flex h-full w-full items-center justify-center p-6 text-center text-xs"
                  style={{ color: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
                >
                  No terminal sessions. Click + to start one.
                </div>
              ) : (
                sessions.map((s) => (
                  <div
                    key={s.id}
                    className="absolute inset-0"
                    style={{ display: s.id === activeSessionId ? 'block' : 'none' }}
                  >
                    <TerminalPane
                      sessionId={s.id}
                      visible={s.id === activeSessionId}
                      onEvicted={handleEvicted}
                    />
                  </div>
                ))
              )}
            </div>
          </>
        )}
      </div>

      {toastMsg ? (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-[200] max-w-sm -translate-x-1/2 rounded-md border border-border bg-popover px-4 py-2 text-center text-sm text-popover-foreground shadow-md"
        >
          {toastMsg}
        </div>
      ) : null}
    </>
  )
}
