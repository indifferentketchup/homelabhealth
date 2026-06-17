import { useEffect, useRef } from 'react'

const DEFAULT_THRESHOLD_MS = 500
const DEFAULT_MOVE_TOLERANCE_PX = 10

/**
 * Hook: fire `onLongPress(syntheticEvent)` after a 500ms hold on touch.
 * Returns touch handlers to spread onto the target element. Cancels on
 * finger move > 10px or early release.
 *
 * The synthetic event is a plain object with `{ clientX, clientY, currentTarget,
 * preventDefault(), stopPropagation() }`  -  enough to reuse the same callback
 * the desktop onContextMenu uses (which typically reads clientX/clientY to
 * position a popover).
 *
 * After a successful long-press, onTouchEnd calls e.preventDefault() to
 * suppress the synthetic click on most browsers. Callers that need a harder
 * guard can check the returned `didFireRef.current` inside their onClick.
 *
 * Haptic feedback via navigator.vibrate(12) if available.
 *
 * Usage:
 *   const lp = useLongPress(handleContextMenu)
 *   return <button onContextMenu={handleContextMenu} {...lp}>…</button>
 */
export function useLongPress(onLongPress, opts = {}) {
  const threshold = opts.threshold ?? DEFAULT_THRESHOLD_MS
  const moveTolerance = opts.moveTolerance ?? DEFAULT_MOVE_TOLERANCE_PX
  const timerRef = useRef(null)
  const startRef = useRef(null)
  const firedRef = useRef(false)

  const cancel = () => {
    if (timerRef.current) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
    startRef.current = null
  }

  const onTouchStart = (e) => {
    cancel()
    if (!e.touches || e.touches.length === 0) return
    firedRef.current = false
    const t = e.touches[0]
    const target = e.currentTarget
    startRef.current = { x: t.clientX, y: t.clientY, target }
    timerRef.current = window.setTimeout(() => {
      firedRef.current = true
      try { if (navigator.vibrate) navigator.vibrate(12) } catch { /* non-fatal */ }
      onLongPress({
        clientX: startRef.current?.x ?? 0,
        clientY: startRef.current?.y ?? 0,
        currentTarget: startRef.current?.target ?? target,
        preventDefault: () => {},
        stopPropagation: () => {},
      })
    }, threshold)
  }

  const onTouchMove = (e) => {
    if (!startRef.current) return
    const t = e.touches[0]
    if (!t) return
    const dx = Math.abs(t.clientX - startRef.current.x)
    const dy = Math.abs(t.clientY - startRef.current.y)
    if (dx > moveTolerance || dy > moveTolerance) cancel()
  }

  const onTouchEnd = (e) => {
    if (firedRef.current) e.preventDefault()
    cancel()
  }
  const onTouchCancel = () => cancel()

  useEffect(() => () => cancel(), [])

  return { onTouchStart, onTouchMove, onTouchEnd, onTouchCancel, didFireRef: firedRef }
}
