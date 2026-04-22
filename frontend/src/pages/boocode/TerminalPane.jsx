import { useCallback, useEffect, useRef } from 'react'
import '@xterm/xterm/css/xterm.css'

import { useTerminalSession } from '@/hooks/useTerminalSession.js'

export default function TerminalPane({ sessionId, visible, onEvicted }) {
  const hostRef = useRef(null)
  const roRef = useRef(null)

  const handleEvicted = useCallback(
    (payload) => {
      if (typeof onEvicted === 'function') onEvicted(sessionId, payload)
    },
    [onEvicted, sessionId],
  )

  const { attachTo, fitOnVisible } = useTerminalSession(sessionId, {
    onEvicted: handleEvicted,
  })

  useEffect(() => {
    const node = hostRef.current
    if (!node) return
    attachTo(node)

    // Refit whenever the host's box changes (drawer resize, tab switch-in,
    // viewport resize). xterm doesn't track layout on its own.
    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => {
        fitOnVisible()
      })
      ro.observe(node)
      roRef.current = ro
    }
    return () => {
      if (roRef.current) {
        try { roRef.current.disconnect() } catch { /* ignore */ }
        roRef.current = null
      }
    }
  }, [attachTo, fitOnVisible])

  // Tab switch-in: the host box exists but xterm might have been measured
  // against a zero-height collapsed drawer. Fit once we're visible again.
  useEffect(() => {
    if (!visible) return
    const handle = window.setTimeout(() => fitOnVisible(), 0)
    return () => window.clearTimeout(handle)
  }, [visible, fitOnVisible])

  return (
    <div
      className="h-full w-full min-h-0 min-w-0"
      style={{
        display: visible ? 'block' : 'none',
        background: '#0a0604',
        padding: '6px 8px 0',
      }}
    >
      <div ref={hostRef} className="h-full w-full" />
    </div>
  )
}
