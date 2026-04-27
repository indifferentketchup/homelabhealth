import { ArrowDown, ArrowUp, Minus, Plus, RotateCcw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  HOTKEY_CATALOG,
  getHotkey,
  useTerminalHotkeysStore,
} from '@/store/terminalHotkeysStore.js'

export default function HotkeysSettingsTab() {
  const bar = useTerminalHotkeysStore((s) => s.bar)
  const visible = useTerminalHotkeysStore((s) => s.visible)
  const addToBar = useTerminalHotkeysStore((s) => s.addToBar)
  const removeFromBar = useTerminalHotkeysStore((s) => s.removeFromBar)
  const moveBar = useTerminalHotkeysStore((s) => s.moveBar)
  const setVisible = useTerminalHotkeysStore((s) => s.setVisible)
  const reset = useTerminalHotkeysStore((s) => s.reset)

  const inBarSet = new Set(bar)
  const available = HOTKEY_CATALOG.filter((k) => !inBarSet.has(k.id))

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Terminal hotkeys</h3>
        <p className="text-xs text-muted-foreground">
          One-tap keys that appear in a row above the BooCode terminal. The Ctrl key is a
          sticky modifier — tap it to arm, then type a letter to send Ctrl+letter (auto-disarms
          after 5 s).
        </p>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={visible}
          onChange={(e) => setVisible(e.target.checked)}
          className="size-4"
        />
        Show hotkey bar above the terminal
      </label>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            On the bar ({bar.length})
          </h4>
          <Button variant="ghost" size="xs" onClick={reset}>
            <RotateCcw className="mr-1 size-3" /> Reset to defaults
          </Button>
        </div>
        {bar.length === 0 ? (
          <p className="rounded border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            No hotkeys on the bar. Add some from below.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded border border-border">
            {bar.map((id, i) => {
              const entry = getHotkey(id)
              if (!entry) return null
              return (
                <li key={id} className="flex items-center gap-2 px-3 py-2">
                  <span className="flex-1 text-sm" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                    {entry.label}
                    {entry.sticky === 'ctrl' ? (
                      <span className="ml-2 text-xs text-muted-foreground">(sticky modifier)</span>
                    ) : null}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Move up"
                    onClick={() => moveBar(id, 'up')}
                    disabled={i === 0}
                  >
                    <ArrowUp className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Move down"
                    onClick={() => moveBar(id, 'down')}
                    disabled={i === bar.length - 1}
                  >
                    <ArrowDown className="size-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Remove from bar"
                    onClick={() => removeFromBar(id)}
                  >
                    <Minus className="size-3.5" />
                  </Button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Available ({available.length})
        </h4>
        {available.length === 0 ? (
          <p className="rounded border border-dashed border-border px-3 py-4 text-center text-xs text-muted-foreground">
            All catalog keys are on the bar.
          </p>
        ) : (
          <ul className="divide-y divide-border rounded border border-border">
            {available.map((entry) => (
              <li key={entry.id} className="flex items-center gap-2 px-3 py-2">
                <span className="flex-1 text-sm" style={{ fontFamily: "'JetBrains Mono', monospace" }}>
                  {entry.label}
                </span>
                <Button
                  variant="ghost"
                  size="icon-xs"
                  aria-label="Add to bar"
                  onClick={() => addToBar(entry.id)}
                >
                  <Plus className="size-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
