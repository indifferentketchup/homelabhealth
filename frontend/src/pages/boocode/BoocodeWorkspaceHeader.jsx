import { Columns2, MessageSquare, TerminalSquare } from 'lucide-react'

import { Button } from '@/components/ui/button'

/**
 * BoocodeWorkspaceHeader
 *
 * Small prompt-style header strip rendered above BoocodeCenterPane.
 * Shows the DAW name and two toggle buttons.
 *
 * Props:
 *  - dawName:        string | null   — displayed after the prompt sigil
 *  - primary:        'chat' | 'terminal'
 *  - split:          boolean
 *  - onCyclePrimary: () => void      — flips primary between 'chat' and 'terminal'
 *  - onToggleSplit:  () => void      — flips split on/off
 *
 * Desktop (≥md, 768px): two buttons side-by-side — [CHAT ⇄ / TERM ⇄] + [⇔ SPLIT]
 * Mobile (<md):         only the cycle button; split button hidden.
 */
export default function BoocodeWorkspaceHeader({
  dawName,
  primary,
  split,
  onCyclePrimary,
  onToggleSplit,
}) {
  const isTerm = primary === 'terminal'

  return (
    <div
      className="bc-prompt-line flex shrink-0 items-center gap-2 border-b px-3 py-1 min-h-[2.75rem] md:min-h-[2rem]"
      style={{
        borderColor: 'var(--border)',
        background: 'var(--bg-card)',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {/* Prompt sigil */}
      <span style={{ color: 'var(--orange, #ff8c00)', fontSize: '0.75rem' }}>$</span>

      {/* DAW name */}
      <span
        className="truncate text-xs"
        style={{ color: 'var(--text)', minWidth: 0 }}
        title={dawName ?? undefined}
      >
        {dawName ?? 'boocode'}
      </span>

      <div className="ml-auto flex items-center gap-1.5">
        {/* Cycle primary button — shown on all screen sizes */}
        <Button
          variant="outline"
          size="xs"
          onClick={onCyclePrimary}
          className="h-11 px-4 md:h-7 md:px-2.5"
          style={{
            borderColor: 'var(--orange, #ff8c00)',
            color: 'var(--orange, #ff8c00)',
            background: 'var(--bg-card)',
          }}
          aria-label={isTerm ? 'Switch to chat view' : 'Switch to terminal view'}
          title={isTerm ? 'Switch to chat (Ctrl+`)' : 'Switch to terminal (Ctrl+`)'}
        >
          {isTerm ? (
            <TerminalSquare className="size-3 shrink-0" />
          ) : (
            <MessageSquare className="size-3 shrink-0" />
          )}
          <span className="uppercase tracking-wide">
            {isTerm ? 'TERM' : 'CHAT'}
            {' '}⇄
          </span>
        </Button>

        {/* Split toggle — desktop only (hidden below md) */}
        <Button
          variant={split ? 'default' : 'outline'}
          size="xs"
          onClick={onToggleSplit}
          aria-pressed={split}
          className="hidden md:inline-flex"
          style={
            split
              ? undefined
              : { borderColor: 'var(--border)', color: 'var(--text)', background: 'transparent' }
          }
          title={split ? 'Close split view' : 'Open split view (chat + terminal side by side)'}
        >
          <Columns2 className="size-3 shrink-0" />
          <span className="uppercase tracking-wide">⇔ SPLIT</span>
        </Button>
      </div>
    </div>
  )
}
