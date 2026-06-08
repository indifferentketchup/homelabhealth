import { cn } from '@/lib/utils'

const SVG_GLYPH = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M4 8v2a4 4 0 0 0 4 4h4a4 4 0 0 0 4-4V8" />
    <path d="M16 2v2a4 4 0 0 1-4 4h-1" />
    <path d="M8 2v2a4 4 0 0 0 4 4" />
    <path d="M19 15v6" />
    <path d="M16 18h6" />
    <circle cx="19" cy="15" r="3" />
  </svg>
)

/**
 * Static assistant glyph: SVG stethoscope icon. `kind` controls sizing across
 * the selector trigger, dropdown rows, plus-menu rows, and message bubbles.
 */
export function AssistantGlyph({ kind = 'list', className }) {
  if (kind === 'header') {
    return (
      <div
        className={cn(
          'flex size-20 shrink-0 items-center justify-center rounded-full border border-border bg-card text-muted-foreground',
          className,
        )}
        aria-hidden
      >
        <span className="size-10">{SVG_GLYPH}</span>
      </div>
    )
  }

  if (kind === 'trigger') {
    return (
      <span className={cn('inline-flex', className)} aria-hidden>
        <span className="size-4">{SVG_GLYPH}</span>
      </span>
    )
  }

  if (kind === 'list') {
    return (
      <span
        className={cn('flex size-6 shrink-0 items-center justify-center', className)}
        aria-hidden
      >
        <span className="size-4">{SVG_GLYPH}</span>
      </span>
    )
  }

  const framed =
    kind === 'bubble'
      ? 'flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground'
      : 'flex size-4 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground'

  return (
    <span className={cn(framed, className)} aria-hidden>
      <span className={kind === 'bubble' ? 'size-4' : 'size-3'}>{SVG_GLYPH}</span>
    </span>
  )
}
