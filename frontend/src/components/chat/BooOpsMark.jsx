import { cn } from '@/lib/utils'

/** Circular BooOps placeholder until real assets ship. */
export function BooOpsMark({ className, label = 'B' }) {
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-center rounded-full border border-border bg-card font-semibold text-muted-foreground',
        className,
      )}
      aria-hidden
    >
      {label}
    </div>
  )
}
