import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChartColumnIncreasing } from 'lucide-react'

import { getTokenAnalytics } from '@/api/analytics.js'
import { cn } from '@/lib/utils'

function fmt(n) {
  if (n == null || Number.isNaN(n)) return '0'
  return Number(n).toLocaleString()
}

function pct(numerator, denominator) {
  if (!denominator || !numerator) return 0
  return Math.min(100, Math.round((numerator / denominator) * 100))
}

function shortDate(iso) {
  if (!iso) return ' - '
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ' - '
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function shortDuration(startIso, endIso) {
  if (!startIso || !endIso) return ' - '
  const s = new Date(startIso).getTime()
  const e = new Date(endIso).getTime()
  if (Number.isNaN(s) || Number.isNaN(e)) return ' - '
  const diff = Math.max(0, e - s)
  if (diff < 60000) return '<1m'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const rm = mins % 60
  return rm ? `${hrs}h ${rm}m` : `${hrs}h`
}

function StatCard({ label, value, sub }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-foreground">{fmt(value)}</p>
      {sub != null && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  )
}

function InlineBar({ value, max, color = 'bg-primary' }) {
  const w = max > 0 ? (value / max) * 100 : 0
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
      <div className={cn('h-full rounded-full transition-all duration-300', color)} style={{ width: `${Math.min(100, w)}%` }} />
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16 text-center">
      <ChartColumnIncreasing className="size-12 text-muted-foreground/40" />
      <p className="text-lg font-medium text-muted-foreground">No usage data yet</p>
      <p className="max-w-xs text-sm text-muted-foreground/60">
        Token usage data will appear here once you start chatting with your workspaces.
      </p>
    </div>
  )
}

function SessionsTab({ sessions }) {
  const maxTokens = Math.max(1, ...sessions.map((s) => s.total_tokens || 0))

  if (!sessions || sessions.length === 0) {
    return <EmptyState />
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <th className="py-3 pr-4">Chat</th>
            <th className="py-3 pr-4">Model</th>
            <th className="py-3 pr-4 text-right tabular-nums">Msgs</th>
            <th className="py-3 pr-4 text-right tabular-nums">Tokens</th>
            <th className="py-3 pr-4 text-right tabular-nums">Prompt</th>
            <th className="py-3 pr-4 text-right tabular-nums">Completion</th>
            <th className="py-3 pr-4">Last activity</th>
            <th className="py-3" aria-label="Bar" />
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
              <td className="max-w-40 truncate py-3 pr-4 font-medium text-foreground" title={s.title || 'Untitled chat'}>
                {s.title || 'Untitled chat'}
              </td>
              <td className="py-3 pr-4 text-muted-foreground">{s.chat_model || ' - '}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(s.message_count)}</td>
              <td className="py-3 pr-4 text-right tabular-nums font-medium text-foreground">{fmt(s.total_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(s.total_prompt_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(s.total_completion_tokens)}</td>
              <td className="whitespace-nowrap py-3 pr-4 text-muted-foreground">{shortDate(s.last_message_at)}</td>
              <td className="w-24 py-3">
                <InlineBar value={s.total_tokens || 0} max={maxTokens} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ToolCostsTab({ models }) {
  const maxTokens = Math.max(1, ...models.map((m) => m.total_tokens || 0))
  const total = models.reduce((s, m) => s + (m.total_tokens || 0), 0)

  if (!models || models.length === 0) {
    return <EmptyState />
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <th className="py-3 pr-4">Model</th>
            <th className="py-3 pr-4 text-right tabular-nums">Messages</th>
            <th className="py-3 pr-4 text-right tabular-nums">Total tokens</th>
            <th className="py-3 pr-4 text-right tabular-nums">Prompt</th>
            <th className="py-3 pr-4 text-right tabular-nums">Completion</th>
            <th className="py-3 pr-4 text-right tabular-nums">Share</th>
            <th className="py-3" aria-label="Bar" />
          </tr>
        </thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
              <td className="py-3 pr-4 font-medium text-foreground">{m.model}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(m.message_count)}</td>
              <td className="py-3 pr-4 text-right tabular-nums font-medium text-foreground">{fmt(m.total_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(m.total_prompt_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(m.total_completion_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{pct(m.total_tokens, total)}%</td>
              <td className="w-24 py-3">
                <InlineBar value={m.total_tokens || 0} max={maxTokens} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ProviderCompareTab({ providers }) {
  const maxTokens = Math.max(1, ...providers.map((p) => p.total_tokens || 0))

  if (!providers || providers.length === 0) {
    return <EmptyState />
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <th className="py-3 pr-4">Provider</th>
            <th className="py-3 pr-4">Type</th>
            <th className="py-3 pr-4 text-right tabular-nums">Messages</th>
            <th className="py-3 pr-4 text-right tabular-nums">Total tokens</th>
            <th className="py-3 pr-4 text-right tabular-nums">Prompt</th>
            <th className="py-3 pr-4 text-right tabular-nums">Completion</th>
            <th className="py-3" aria-label="Bar" />
          </tr>
        </thead>
        <tbody>
          {providers.map((p) => (
            <tr key={p.provider_name} className="border-b border-border/50 last:border-0 hover:bg-muted/30">
              <td className="py-3 pr-4 font-medium text-foreground">
                {p.provider_name}
              </td>
              <td className="py-3 pr-4">
                <span className={cn(
                  'inline-block rounded-full px-2 py-0.5 text-[11px] font-medium',
                  p.is_bundled
                    ? 'bg-primary/10 text-primary'
                    : 'bg-amber-500/10 text-amber-600 dark:text-amber-400',
                )}>
                  {p.is_bundled ? 'Bundled' : 'External'}
                </span>
              </td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(p.message_count)}</td>
              <td className="py-3 pr-4 text-right tabular-nums font-medium text-foreground">{fmt(p.total_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(p.total_prompt_tokens)}</td>
              <td className="py-3 pr-4 text-right tabular-nums text-muted-foreground">{fmt(p.total_completion_tokens)}</td>
              <td className="w-24 py-3">
                <InlineBar value={p.total_tokens || 0} max={maxTokens} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const TABS = [
  { id: 'sessions', label: 'Session Usage' },
  { id: 'models', label: 'Tool Costs' },
  { id: 'providers', label: 'Provider Compare' },
]

export default function AnalyticsPage() {
  const [tab, setTab] = useState('sessions')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['analytics', 'tokens'],
    queryFn: getTokenAnalytics,
    staleTime: 30_000,
  })

  const summary = data?.summary
  const sessions = data?.sessions ?? []
  const models = data?.models ?? []
  const providers = data?.providers ?? []

  const hasData = useMemo(() => {
    return (
      (summary?.total_tokens ?? 0) > 0 ||
      sessions.length > 0
    )
  }, [summary, sessions])

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-4">
        <h1 className="fs-heading font-semibold tracking-tight text-foreground">Usage Analytics</h1>
        {!isLoading && hasData && (
          <p className="text-xs text-muted-foreground">
            {fmt(summary?.chat_count)} chats &middot; {fmt(summary?.message_count)} messages
          </p>
        )}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        {isLoading ? (
          <div className="flex flex-1 items-center justify-center">
            <p className="text-sm text-muted-foreground">Loading&hellip;</p>
          </div>
        ) : isError ? (
          <div className="flex flex-1 items-center justify-center">
            <p className="text-sm text-destructive">Failed to load analytics. Try again.</p>
          </div>
        ) : !hasData ? (
          <EmptyState />
        ) : (
          <>
            {/* Summary cards */}
            <div className="grid shrink-0 grid-cols-2 gap-3 border-b border-border px-4 py-4 sm:grid-cols-4">
              <StatCard label="Total chats" value={summary?.chat_count} />
              <StatCard label="Total messages" value={summary?.message_count} />
              <StatCard label="Total tokens" value={summary?.total_tokens} />
              <StatCard
                label="Avg tokens / message"
                value={summary?.message_count > 0 ? Math.round(summary.total_tokens / summary.message_count) : 0}
              />
            </div>

            {/* Tabs */}
            <div className="shrink-0 overflow-x-auto border-b border-border" role="tablist" aria-label="Analytics sections">
              <div className="flex flex-row px-4">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    id={`analytics-tab-${t.id}`}
                    type="button"
                    role="tab"
                    aria-selected={tab === t.id}
                    aria-controls={`analytics-panel-${t.id}`}
                    onClick={() => setTab(t.id)}
                    className={cn(
                      'shrink-0 px-4 py-3 text-sm whitespace-nowrap transition-colors',
                      tab === t.id
                        ? 'border-b-2 border-primary font-medium text-foreground'
                        : 'border-b-2 border-transparent text-muted-foreground hover:text-foreground',
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Tab panels */}
            <div
              id={`analytics-panel-${tab}`}
              role="tabpanel"
              aria-labelledby={`analytics-tab-${tab}`}
              className="min-h-0 flex-1 overflow-y-auto px-4 py-4"
            >
              {tab === 'sessions' && <SessionsTab sessions={sessions} />}
              {tab === 'models' && <ToolCostsTab models={models} />}
              {tab === 'providers' && <ProviderCompareTab providers={providers} />}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
