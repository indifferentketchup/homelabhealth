import { useQuery } from '@tanstack/react-query'
import { getContextBarSetting } from '@/api/settings.js'

function abbreviateTokens(n) {
  if (n == null || n <= 0) return '0'
  if (n < 1000) return String(n)
  const k = n / 1000
  if (k < 10) return `${k.toFixed(1)}K`
  return `${Math.round(k)}K`
}

function tierColor(ratio) {
  if (ratio > 0.95) return 'text-red-500'
  if (ratio > 0.8) return 'text-orange-500'
  if (ratio > 0.6) return 'text-amber-500'
  return 'text-muted-foreground/60'
}

export function ContextIndicator({ promptTokens, ctxMax }) {
  const { data: setting } = useQuery({
    queryKey: ['settings', 'context-bar'],
    queryFn: getContextBarSetting,
    staleTime: 30_000,
  })

  const show = setting?.show_context_bar === true || setting?.show_context_bar === 'true'
  if (!show) return null
  if (!promptTokens || promptTokens <= 0) return null
  if (!ctxMax || ctxMax <= 0) return null

  const ratio = promptTokens / ctxMax
  const color = tierColor(ratio)

  return (
    <div className="flex justify-end pt-0.5 pr-1">
      <span className="inline-flex items-center gap-1 text-[10px] leading-none select-none">
        <span className={color}>●</span>
        <span className="font-mono text-muted-foreground/70">
          {abbreviateTokens(promptTokens)} / {abbreviateTokens(ctxMax)}
        </span>
      </span>
    </div>
  )
}
