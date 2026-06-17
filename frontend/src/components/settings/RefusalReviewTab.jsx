import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { getRefusals } from '@/api/audit.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

const PAGE_SIZE = 50

function formatDate(iso) {
  if (!iso) return ' - '
  try {
    const d = new Date(iso)
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function TypeBadge({ action }) {
  const isInput = action === 'safeguard.refuse.input'
  return (
    <span
      className={cn(
        'inline-block rounded-full px-2 py-0.5 text-[11px] font-medium',
        isInput
          ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
          : 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
      )}
    >
      {isInput ? 'Input blocked' : 'Output flagged'}
    </span>
  )
}

export default function RefusalReviewTab() {
  const [offset, setOffset] = useState(0)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['refusals', offset],
    queryFn: () => getRefusals({ limit: PAGE_SIZE, offset }),
    keepPreviousData: true,
  })

  const rows = data?.rows ?? []
  const total = data?.total ?? 0
  const hasMore = offset + PAGE_SIZE < total

  const loadMore = useCallback(() => {
    setOffset((prev) => prev + PAGE_SIZE)
  }, [])

  return (
    <section className="mx-auto w-full max-w-3xl space-y-5">
      <div>
        <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">
          Safety Log
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          History of content blocked by input scanning or flagged by output scanning.
        </p>
      </div>

      {isLoading && offset === 0 ? (
        <p className="text-sm text-muted-foreground">Loading safety events...</p>
      ) : isError ? (
        <p className="text-sm text-destructive">
          {error instanceof Error ? error.message : 'Failed to load safety events.'}
        </p>
      ) : rows.length === 0 && offset === 0 ? (
        <div className="rounded-lg border border-border bg-card p-6 text-center">
          <p className="text-sm text-muted-foreground">
            No safety events recorded yet. This panel shows when the system blocks or flags content.
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full table-auto text-sm">
              <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Date</th>
                  <th className="px-3 py-2 font-medium">Type</th>
                  <th className="px-3 py-2 font-medium">Target</th>
                  <th className="px-3 py-2 font-medium">Details</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-border align-top">
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                      {formatDate(row.ts)}
                    </td>
                    <td className="px-3 py-2">
                      <TypeBadge action={row.action} />
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-foreground">
                      {row.target_type || ' - '}
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                      {row.target_id || ' - '}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              Showing {Math.min(offset + PAGE_SIZE, total)} of {total} event{total === 1 ? '' : 's'}
            </span>
            {hasMore ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={loadMore}
                disabled={isLoading}
              >
                {isLoading ? 'Loading...' : 'Load more'}
              </Button>
            ) : null}
          </div>
        </>
      )}
    </section>
  )
}
