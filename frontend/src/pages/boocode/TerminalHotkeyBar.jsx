import { useCallback } from 'react'

import { getHotkey, useTerminalHotkeysStore } from '@/store/terminalHotkeysStore.js'

export default function TerminalHotkeyBar({ api }) {
  const bar = useTerminalHotkeysStore((s) => s.bar)
  const visible = useTerminalHotkeysStore((s) => s.visible)
  const ctrlArmed = api?.ctrlArmed ?? false

  // Stop the touch from reaching the terminal pane below (which calls
  // preventDefault on touchmove to suppress page-scroll). We don't want a
  // tap-and-drag on a hotkey button to also scroll the terminal buffer.
  const stopTouch = useCallback((e) => e.stopPropagation(), [])

  const handlePress = useCallback(
    (entry) => {
      if (!api) return
      if (entry.sticky === 'ctrl') {
        api.armCtrl()
        return
      }
      if (entry.bytes != null) {
        api.sendInput(entry.bytes)
      }
    },
    [api],
  )

  if (!visible || bar.length === 0) return null

  return (
    <div
      className="flex shrink-0 items-center gap-1 overflow-x-auto border-b px-2 py-1"
      style={{
        borderColor: 'var(--border)',
        background: 'var(--bg-card)',
        scrollbarWidth: 'thin',
        WebkitOverflowScrolling: 'touch',
        // Suppress iOS native gesture interference for swipes that start on
        // this bar (e.g. swipe-back). Pinch-zoom etc. still passes through.
        touchAction: 'pan-x',
      }}
      role="toolbar"
      aria-label="Terminal hotkeys"
      onTouchStart={stopTouch}
      onTouchMove={stopTouch}
    >
      {bar.map((id) => {
        const entry = getHotkey(id)
        if (!entry) return null
        const isCtrl = entry.sticky === 'ctrl'
        const armed = isCtrl && ctrlArmed
        return (
          <button
            key={id}
            type="button"
            onClick={() => handlePress(entry)}
            disabled={!api}
            className="shrink-0 rounded border px-2 py-0.5 text-xs transition-colors disabled:opacity-50"
            style={{
              borderColor: armed ? 'var(--orange, #ff8c00)' : 'var(--border)',
              color: armed ? '#0a0604' : 'var(--text)',
              background: armed ? 'var(--orange, #ff8c00)' : 'transparent',
              fontFamily: "'JetBrains Mono', monospace",
              minHeight: 28,
              minWidth: 36,
              WebkitTouchCallout: 'none',
              userSelect: 'none',
            }}
            aria-pressed={isCtrl ? armed : undefined}
            aria-label={entry.label}
          >
            {entry.label}
          </button>
        )
      })}
    </div>
  )
}
