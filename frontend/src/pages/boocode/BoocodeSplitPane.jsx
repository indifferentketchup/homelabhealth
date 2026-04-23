import { useCallback, useEffect, useRef, useState } from 'react'

const RATIO_MIN = 0.2
const RATIO_MAX = 0.8

/**
 * BoocodeSplitPane
 *
 * Horizontal flex split with a draggable vertical handle between two panes.
 * Ratio is the fraction of the total width allocated to the LEFT pane.
 * Clamped to [0.2, 0.8] so neither side can be hidden.
 *
 * Props:
 *  - ratio:           number        — 0..1, fraction for left pane
 *  - onRatioChange:   (next: number) => void
 *  - left:            ReactNode
 *  - right:           ReactNode
 *  - ariaLabelLeft?:  string        — defaults to "Primary pane"
 *  - ariaLabelRight?: string        — defaults to "Secondary pane"
 */
export default function BoocodeSplitPane({
  ratio,
  onRatioChange,
  left,
  right,
  ariaLabelLeft = 'Primary pane',
  ariaLabelRight = 'Secondary pane',
}) {
  // dragging state tracked in React state (not ref) to conditionally disable
  // CSS transitions — reading ref.current during render is a lint error under
  // react-hooks/refs.
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef({ startX: 0, startRatio: 0, containerW: 0 })
  const containerRef = useRef(null)

  const clamp = (v) => Math.max(RATIO_MIN, Math.min(RATIO_MAX, v))

  const handleDragStart = useCallback(
    (e) => {
      e.preventDefault()
      const clientX = e.touches ? e.touches[0].clientX : e.clientX
      const w = containerRef.current ? containerRef.current.getBoundingClientRect().width : 0
      dragRef.current = { startX: clientX, startRatio: ratio, containerW: w }
      setDragging(true)
    },
    [ratio],
  )

  useEffect(() => {
    if (!dragging) return
    function onMove(e) {
      const clientX = e.touches ? e.touches[0].clientX : e.clientX
      const { startX, startRatio, containerW } = dragRef.current
      if (containerW === 0) return
      const dx = clientX - startX
      const delta = dx / containerW
      onRatioChange(clamp(startRatio + delta))
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
      window.removeEventListener('touchmove', onMove, { passive: false })
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchend', onUp)
    }
  // onRatioChange is a state setter from the parent — it's stable (setSplitRatio).
  // Including it in deps would re-register pointer listeners on every ratio tick
  // mid-drag, causing the effect to tear down and re-mount while the user is
  // dragging. Intentional omission: see TerminalDrawer.jsx:259 for the same pattern.
  }, [dragging]) // eslint-disable-line react-hooks/exhaustive-deps

  const leftPct = `${(ratio * 100).toFixed(2)}%`
  const rightPct = `${((1 - ratio) * 100).toFixed(2)}%`
  const transition = dragging ? 'none' : 'flex-basis 120ms ease-out'

  return (
    <div
      ref={containerRef}
      className="flex min-h-0 flex-1 overflow-hidden"
      style={{ flexDirection: 'row', userSelect: dragging ? 'none' : undefined }}
    >
      {/* Left pane */}
      <div
        aria-label={ariaLabelLeft}
        className="flex min-h-0 min-w-0 flex-col overflow-hidden"
        style={{ flexBasis: leftPct, flexShrink: 0, flexGrow: 0, transition }}
      >
        {left}
      </div>

      {/* Drag handle */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize split panes"
        tabIndex={-1}
        className="group relative flex w-2 shrink-0 cursor-col-resize select-none items-center justify-center"
        onMouseDown={handleDragStart}
        onTouchStart={handleDragStart}
        style={{
          background: 'transparent',
          borderLeft: '1px solid var(--border)',
          borderRight: '1px solid var(--border)',
        }}
      >
        {/* Center pill affordance */}
        <div
          className="w-[3px] rounded-full opacity-50 transition-opacity group-hover:opacity-100"
          style={{
            height: '48px',
            background: 'var(--orange, #ff8c00)',
          }}
        />
      </div>

      {/* Right pane */}
      <div
        aria-label={ariaLabelRight}
        className="flex min-h-0 min-w-0 flex-col overflow-hidden"
        style={{ flexBasis: rightPct, flexShrink: 0, flexGrow: 0, transition }}
      >
        {right}
      </div>
    </div>
  )
}
