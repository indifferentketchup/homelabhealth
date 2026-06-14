import { cn } from '@/lib/utils'

export function TierRadio({ tier, selected, onSelect, isRecommended, disabled }) {
  const checked = selected === tier.id
  return (
    <label
      className={cn(
        'flex cursor-pointer flex-col gap-1.5 rounded-lg border bg-card p-3 transition-colors',
        checked ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-foreground/30',
        disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <div className="flex items-center gap-2">
        <input
          type="radio"
          name="system-tier"
          value={tier.id}
          checked={checked}
          onChange={() => onSelect(tier.id)}
          disabled={disabled}
          className="size-4 shrink-0 accent-primary"
          data-testid={`system-tier-${tier.id}`}
        />
        <span className="text-sm font-medium text-foreground">{tier.label}</span>
        <span className="ml-1 font-mono text-[11px] text-muted-foreground">{tier.id}</span>
        {isRecommended ? (
          <span className="ml-auto rounded-full bg-primary/15 px-2 py-0.5 text-[11px] font-medium text-foreground">
            recommended
          </span>
        ) : null}
      </div>
      <div className="grid grid-cols-1 gap-x-4 gap-y-0.5 pl-6 text-xs text-muted-foreground sm:grid-cols-2">
        <div>Detect: <span className="text-foreground">{tier.detect}</span></div>
        <div>Footprint: <span className="text-foreground">{tier.footprint}</span></div>
        <div>Chat: <span className="text-foreground">{tier.chat}</span></div>
        <div>Embed: <span className="text-foreground">{tier.embed}</span></div>
        <div>Rerank: <span className="text-foreground">{tier.rerank}</span></div>
        <div>Vision: <span className="text-foreground">{tier.vision}</span></div>
      </div>
    </label>
  )
}
