import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'

import { wsUrl } from '@/api/terminals.js'

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000]

// Mobile touch-drag scrollback. xterm.js doesn't ship touch scroll: desktop
// mouse wheel works against the 5000-line scrollback, but touch yields
// nothing. We translate one-finger vertical drag into term.scrollLines.
//
// Skips when:
//  - multi-touch (pinch/zoom passes through)
//  - alternate screen (claude/opencode TUIs handle their own history; the
//    main scrollback is empty for alt-screen apps anyway)
//
// Listeners live on the host node and die with it on DOM removal; xterm
// doesn't preventDefault on touch, so our handlers run normally alongside
// xterm's own keystroke/focus logic. Marker on the node prevents
// double-binding if attachTo is called twice for the same node.
function attachTouchScroll(node, term) {
  if (!node || node.__bcTouchScrollBound) return
  node.__bcTouchScrollBound = true
  let lastY = 0
  let active = false
  const onStart = (e) => {
    if (e.touches.length !== 1) {
      active = false
      return
    }
    lastY = e.touches[0].clientY
    active = true
  }
  const onMove = (e) => {
    if (!active || e.touches.length !== 1) return
    if (term.buffer?.active?.type === 'alternate') return
    const y = e.touches[0].clientY
    const dy = y - lastY
    const lineHeight = (term.options?.fontSize || 13) * 1.2
    const lines = Math.round(dy / lineHeight)
    if (lines !== 0) {
      term.scrollLines(-lines)
      lastY = y
      e.preventDefault()
    }
  }
  const onEnd = () => {
    active = false
  }
  // Capture phase: fires before xterm.js's own touch listeners on the
  // child elements, so even if xterm stopPropagation()s for its selection
  // logic, our scroll handler still sees the events.
  node.addEventListener('touchstart', onStart, { passive: true, capture: true })
  // touchmove must NOT be passive so preventDefault can suppress page-scroll.
  node.addEventListener('touchmove', onMove, { passive: false, capture: true })
  node.addEventListener('touchend', onEnd, { passive: true, capture: true })
  node.addEventListener('touchcancel', onEnd, { passive: true, capture: true })
}

// Frame contract (see spec + backend/routers/terminals.py):
//   server → client, text frame:  JSON control (init, eviction, resize ack)
//   server → client, binary:      raw PTY bytes (first = capture-pane replay)
//   client → server, binary:      user keystrokes
//   client → server, text:        {type: "resize", cols, rows}
export function useTerminalSession(sessionId, { onEvicted } = {}) {
  const termRef = useRef(null)
  const fitRef = useRef(null)
  const wsRef = useRef(null)
  const containerRef = useRef(null)
  const reconnectTimerRef = useRef(null)
  const reconnectAttemptRef = useRef(0)
  const mountedRef = useRef(false)
  const closedByUserRef = useRef(false)
  const lastSizeRef = useRef({ cols: 80, rows: 24 })
  const connectRef = useRef(null)

  const [connected, setConnected] = useState(false)
  const [deviceCount, setDeviceCount] = useState(0)

  const ensureTerminal = useCallback(() => {
    if (termRef.current) return termRef.current
    // On mobile viewports (<768px) the screen is too narrow for 13px to fit
    // enough columns for TUIs like opencode. Drop to 11px to gain ~9 extra cols
    // (≈50 → ≈59 on a 390px iPhone) while staying readable.
    const fontSize = typeof window !== 'undefined' && window.innerWidth < 768 ? 11 : 13
    const term = new Terminal({
      convertEol: true,
      cursorBlink: true,
      allowProposedApi: true,
      fontFamily: "'JetBrains Mono', 'Fira Code', Menlo, monospace",
      fontSize,
      theme: {
        background: '#0a0604',
        foreground: '#f4ece2',
        cursor: '#ff8c00',
        cursorAccent: '#0a0604',
      },
      scrollback: 5000,
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.loadAddon(new WebLinksAddon())
    termRef.current = term
    fitRef.current = fit
    term.onData((data) => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      ws.send(new TextEncoder().encode(data))
    })
    term.onResize(({ cols, rows }) => {
      lastSizeRef.current = { cols, rows }
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      try {
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
      } catch {
        /* ignore */
      }
    })
    return term
  }, [])

  const attachTo = useCallback((node) => {
    containerRef.current = node
    if (!node) return
    const term = ensureTerminal()
    if (!term.element || term.element.parentElement !== node) {
      while (node.firstChild) node.removeChild(node.firstChild)
      term.open(node)
      attachTouchScroll(node, term)
    }
    try {
      fitRef.current?.fit()
    } catch {
      /* layout not ready yet */
    }
  }, [ensureTerminal])

  const fitOnVisible = useCallback(() => {
    if (!containerRef.current || !termRef.current) return
    try {
      fitRef.current?.fit()
    } catch {
      /* noop */
    }
  }, [])

  const sendResize = useCallback((cols, rows) => {
    if (!termRef.current) return
    try {
      termRef.current.resize(cols, rows)
    } catch {
      /* ignore invalid sizes */
    }
  }, [])

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current || closedByUserRef.current) return
    const attempt = reconnectAttemptRef.current
    const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]
    reconnectAttemptRef.current = attempt + 1
    if (reconnectTimerRef.current) window.clearTimeout(reconnectTimerRef.current)
    reconnectTimerRef.current = window.setTimeout(() => {
      reconnectTimerRef.current = null
      connectRef.current?.()
    }, delay)
  }, [])

  const disconnect = useCallback(() => {
    closedByUserRef.current = true
    if (reconnectTimerRef.current) {
      window.clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    const ws = wsRef.current
    if (ws) {
      try {
        ws.close(1000, 'client-disconnect')
      } catch {
        /* ignore */
      }
      wsRef.current = null
    }
    setConnected(false)
  }, [])

  const connect = useCallback(() => {
    if (!sessionId) return
    if (!mountedRef.current) return
    const existing = wsRef.current
    if (existing && existing.readyState !== WebSocket.CLOSED) return

    const term = ensureTerminal()
    closedByUserRef.current = false

    let ws
    try {
      ws = new WebSocket(wsUrl(sessionId))
    } catch {
      scheduleReconnect()
      return
    }
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws

    const writeDim = (msg) => {
      try {
        term.writeln(`\x1b[2m${msg}\x1b[0m`)
      } catch {
        /* ignore */
      }
    }

    ws.addEventListener('open', () => {
      reconnectAttemptRef.current = 0
      setConnected(true)
      const { cols, rows } = lastSizeRef.current
      try {
        ws.send(JSON.stringify({ type: 'resize', cols, rows }))
      } catch {
        /* ignore */
      }
    })

    ws.addEventListener('message', (ev) => {
      if (typeof ev.data === 'string') {
        try {
          const obj = JSON.parse(ev.data)
          if (obj && obj.type === 'init') {
            term.clear()
            // Do NOT overwrite lastSizeRef with the server's reported size.
            // The server always reports DEFAULT_COLS/ROWS (80×24) in the init
            // frame — updating lastSizeRef would undo the correct size that
            // FitAddon already computed and sent on WS open. Instead, re-send
            // our locally-measured size so the PTY syncs to the xterm viewport.
            const { cols, rows } = lastSizeRef.current
            try {
              ws.send(JSON.stringify({ type: 'resize', cols, rows }))
            } catch {
              /* ignore */
            }
            return
          }
          if (obj && obj.type === 'eviction') {
            writeDim('[session evicted by server]')
            closedByUserRef.current = true
            try { ws.close(1000, 'evicted') } catch { /* ignore */ }
            if (typeof onEvicted === 'function') onEvicted(obj)
            return
          }
        } catch {
          /* ignore malformed */
        }
        return
      }
      if (ev.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(ev.data))
      }
    })

    ws.addEventListener('close', (ev) => {
      setConnected(false)
      wsRef.current = null
      if (closedByUserRef.current) return
      if (ev.code === 4004) {
        writeDim('[session closed]')
        closedByUserRef.current = true
        if (typeof onEvicted === 'function') onEvicted({ type: 'closed' })
        return
      }
      writeDim('[disconnected — reconnecting…]')
      scheduleReconnect()
    })

    ws.addEventListener('error', () => {
      // error fires before close; close handler owns the reconnect.
    })
  }, [sessionId, ensureTerminal, scheduleReconnect, onEvicted])

  // Keep the ref in sync for scheduleReconnect to call without stale closures.
  connectRef.current = connect

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      closedByUserRef.current = true
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current)
        reconnectTimerRef.current = null
      }
      const ws = wsRef.current
      if (ws) {
        try { ws.close(1000, 'unmount') } catch { /* ignore */ }
        wsRef.current = null
      }
      const term = termRef.current
      if (term) {
        try { term.dispose() } catch { /* ignore */ }
        termRef.current = null
        fitRef.current = null
      }
    }
  }, [])

  useEffect(() => {
    if (!sessionId) return
    const handle = window.setTimeout(() => {
      connect()
    }, 0)
    return () => {
      window.clearTimeout(handle)
      disconnect()
      closedByUserRef.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // Mobile keyboard handling. On iOS Safari and Android Chrome the on-screen
  // keyboard shrinks the visual viewport — we refit xterm so it occupies only
  // the visible area (not the rows hidden behind the keyboard) and scroll to
  // the bottom so the prompt/cursor stays in view. Without this, tapping the
  // terminal raises the keyboard but the bottom rows (where the user is
  // typing) sit underneath it.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.visualViewport) return
    const vp = window.visualViewport
    const onResize = () => {
      if (!termRef.current || !fitRef.current) return
      try { fitRef.current.fit() } catch { /* ignore */ }
      try { termRef.current.scrollToBottom() } catch { /* ignore */ }
    }
    vp.addEventListener('resize', onResize)
    return () => vp.removeEventListener('resize', onResize)
  }, [])

  // Note: the document.fonts.ready refit is handled in TerminalPane.jsx
  // (after attachTo) so the fit runs against the live DOM node, not before
  // the terminal element has been opened.

  return {
    attachTo,
    fitOnVisible,
    sendResize,
    connect,
    disconnect,
    connected,
    deviceCount,
    setDeviceCount,
    termRef,
    fitRef,
  }
}
