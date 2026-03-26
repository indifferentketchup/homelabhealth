import { cn } from '@/lib/utils'

/**
 * Persona / BooOps avatar: image, emoji, or fallback letter.
 * When `iconUrl` is set, shows `<img>`; else emoji or `fallbackLetter` (e.g. first initial).
 */
export function BooOpsMark({ className, iconUrl = null, emoji = null, fallbackLetter = 'B' }) {
  if (iconUrl) {
    return (
      <img
        src={iconUrl}
        alt=""
        className={cn('size-20 shrink-0 rounded-full border border-border object-cover', className)}
      />
    )
  }
  return (
    <div
      className={cn(
        'flex size-20 shrink-0 items-center justify-center rounded-full border border-border bg-card text-2xl font-semibold text-muted-foreground',
        className,
      )}
      aria-hidden
    >
      {emoji || fallbackLetter}
    </div>
  )
}
