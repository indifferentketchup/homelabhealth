import { Button } from '@/components/ui/button'

/** Shown when generation stalls (no new tokens for 60s). Pattern from BooCode v1.12.3. */
export function StaleStreamBanner({ onRetry, onDiscard }) {
  return (
    <div
      className="mb-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-500/30 bg-background px-3 py-2 shadow-sm"
      role="alert"
      data-testid="stale-stream-banner"
    >
      <p className="text-sm text-muted-foreground">
        Response is taking longer than expected  -  it may still be running, or the connection may have stalled.
      </p>
      <div className="flex shrink-0 gap-2">
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDiscard}>
          Dismiss
        </Button>
      </div>
    </div>
  )
}
