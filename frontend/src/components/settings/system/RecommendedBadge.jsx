import { TIERS, rationaleFor } from './tierData.js'

export function RecommendedBadge({ recommended, sysinfo }) {
  const tierMeta = TIERS.find((t) => t.id === recommended)
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">Recommended tier</h3>
        <span
          className="inline-block rounded-full bg-primary/15 px-2.5 py-0.5 font-mono text-xs font-medium text-foreground"
          data-testid="system-recommended-tier"
        >
          {recommended || ' - '}
        </span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {tierMeta ? tierMeta.label + '  -  ' : ''}{rationaleFor(sysinfo, recommended)}
      </p>
    </div>
  )
}
