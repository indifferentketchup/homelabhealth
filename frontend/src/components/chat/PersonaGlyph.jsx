import { cn } from '@/lib/utils'

/**
 * Small persona avatar: uploaded image when present, otherwise emoji (default 🤖).
 * `kind` controls sizing: selector bar trigger, dropdown row, plus-menu row, message bubble.
 */
export function PersonaGlyph({ iconUrl, emoji, kind = 'list', className }) {
  const glyph = (emoji && String(emoji).trim()) || '🤖'

  if (iconUrl) {
    const img =
      kind === 'trigger'
        ? 'size-5'
        : kind === 'menu'
          ? 'size-4'
          : kind === 'bubble'
            ? 'size-8'
            : 'size-6'
    return (
      <img
        src={iconUrl}
        alt=""
        className={cn('shrink-0 rounded-full border border-border object-cover', img, className)}
      />
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
