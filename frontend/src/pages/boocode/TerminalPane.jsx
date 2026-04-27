import { useCallback, useEffect, useRef } from 'react'
import '@xterm/xterm/css/xterm.css'

import { useTerminalSession } from '@/hooks/useTerminalSession.js'

export default function TerminalPane({ sessionId, visible, onEvicted, onSessionApi }) {
  const hostRef = useRef(null)
  const roRef = useRef(null)

  const handleEvicted = useCallback(
    (payload) => {
      if (typeof onEvicted === 'function') onEvicted(sessionId, payload)
    },
    [onEvicted, sessionId],
  )

  const { attachTo, fitOnVisible, sendInput, armCtrl, ctrlArmed } = useTerminalSession(
    sessionId,
    { onEvicted: handleEvicted },
  )

  // Publish this pane's send/arm controls (and ctrlArmed flag) up to the host
  // so the on-screen hotkey bar can drive whichever session is active. Re-runs
  // whenever ctrlArmed flips so the Ctrl button can highlight in real time.
  useEffect(() => {
    if (typeof onSessionApi !== 'function') return undefined
    onSessionApi(sessionId, { sendInput, armCtrl, ctrlArmed })
    return () => onSessionApi(sessionId, null)
  }, [sessionId, sendInput, armCtrl, ctrlArmed, onSessionApi])

  useEffect(() => {
    const node = hostRef.current
    if (!node) return
    attachTo(node)

    // Refit once fonts settle. The terminal measures its cell dimensions on
    // open(); if JetBrains Mono hasn't loaded yet the measurement uses the
    // system fallback and computes the wrong cols. We refit here (after
    // attachTo) so fitRef is guaranteed to exist when the promise resolves.
    let fontRafId = null
    document.fonts?.ready?.then(() => {
      fontRafId = requestAnimationFrame(() => fitOnVisible())
    })

    // Second-pass refit: mobile browsers can settle layout slightly late,
    // causing the initial measurement to read a stale clientWidth.
    const delayedFit = window.setTimeout(() => fitOnVisible(), 150)

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
      if (fontRafId !== null) cancelAnimationFrame(fontRafId)
      window.clearTimeout(delayedFit)
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

  // Keep finger drags inside the terminal from scrolling the page or
  // rubber-banding the body on iOS. Listener must be passive: false so
  // preventDefault actually takes effect; touch-action: none on the host
  // div (below) classifies the gesture as non-pannable at touchstart.
  useEffect(() => {
    const el = hostRef.current
    if (!el) return
    const onTouchMove = (e) => { if (e.cancelable) e.preventDefault() }
    el.addEventListener('touchmove', onTouchMove, { passive: false })
    return () => el.removeEventListener('touchmove', onTouchMove)
  }, [])

  return (
    <div
      className="h-full w-full min-h-0 min-w-0"
      style={{
        display: visible ? 'block' : 'none',
        background: '#0a0604',
        // Edge-to-edge: drop the 8px lateral padding so the terminal grid
        // gets the full pane width (matters on narrow mobile viewports
        // where TUIs like opencode need every column).
        paddingTop: 6,
      }}
    >
      <div
        ref={hostRef}
        className="h-full w-full"
        style={{ touchAction: 'none', overscrollBehavior: 'contain' }}
      />
    </div>
  )
}
