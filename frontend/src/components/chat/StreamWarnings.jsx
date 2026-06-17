/** Non-blocking notices shown when retrieval or web search silently degraded. */
export function StreamWarnings({ warnings }) {
  if (!warnings?.length) return null
  return (
    <div className="mb-2 space-y-1" role="status">
      {warnings.map((w, i) => (
        <div
          key={i}
          className="flex items-center justify-center rounded-md border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-sm text-yellow-700 dark:text-yellow-400"
        >
          {w}
        </div>
      ))}
    </div>
  )
}
