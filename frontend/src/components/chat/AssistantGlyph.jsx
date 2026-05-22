import { cn } from '@/lib/utils'

/**
 * Static assistant glyph: stethoscope emoji. `kind` controls sizing across
 * the selector trigger, dropdown rows, plus-menu rows, and message bubbles.
 */
export function AssistantGlyph({ kind = 'list', className }) {
  const glyph = '🩺'

  if (kind === 'header') {
    return (
      <div
        className={cn(
          'flex size-20 shrink-0 items-center justify-center rounded-full border border-border bg-card text-4xl font-semibold text-muted-foreground',
          className,
        )}
        aria-hidden
      >
        {glyph}
      </div>
    )
  }

  if (kind === 'trigger') {
    return (
      <span className={cn('text-base leading-none', className)} aria-hidden>
        {glyph}
      </span>
    )
  }

  if (kind === 'list') {
    return (
      <span
        className={cn('flex size-6 shrink-0 items-center justify-center text-base leading-none', className)}
        aria-hidden
      >
        {glyph}
      </span>
    )
  }

  const framed =
    kind === 'bubble'
      ? 'flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-lg font-medium text-muted-foreground'
      : 'flex size-4 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-xs font-medium text-muted-foreground'

  return (
    <span className={cn(framed, className)} aria-hidden>
      {glyph}
    </span>
  )
}
