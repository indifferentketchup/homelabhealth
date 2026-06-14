import { Button } from '@/components/ui/button'
import { formatGpu } from './tierData.js'
import { GpuEnableCard } from './GpuEnableCard.jsx'

export function HardwareCard({ sysinfo, detectedAt, busy, onRedetect, redetectErr }) {
  const cpu = sysinfo?.cpu_model ?? '—'
  const cpuCores = sysinfo?.cpu_cores
  const ram = sysinfo?.ram_total_gb
  const disk = sysinfo?.disk_free_gb
  const gpus = Array.isArray(sysinfo?.gpus) ? sysinfo.gpus : []
  const arch = sysinfo?.arch ?? '—'
  const osName = sysinfo?.os ?? '—'

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">Detected hardware</h3>
        <span
          className="text-xs text-muted-foreground"
          data-testid="system-detected-at"
        >
          {detectedAt ? `detected ${new Date(detectedAt).toLocaleString()}` : 'not detected yet'}
        </span>
      </div>

      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">OS / arch</dt>
          <dd className="font-mono text-xs text-foreground">{osName} / {arch}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">CPU cores (physical)</dt>
          <dd className="text-foreground">{cpuCores ?? '—'}</dd>
        </div>
        <div className="col-span-1 flex flex-col gap-1 sm:col-span-2">
          <dt className="text-muted-foreground">CPU model</dt>
          <dd className="truncate font-mono text-xs text-foreground" title={cpu}>{cpu}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">RAM</dt>
          <dd className="text-foreground">{ram != null ? `${ram} GB` : '—'}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-muted-foreground">Disk free (root)</dt>
          <dd className="text-foreground">{disk != null ? `${disk} GB` : '—'}</dd>
        </div>
        <div className="col-span-1 flex flex-col gap-1 sm:col-span-2">
          <dt className="text-muted-foreground">GPU(s)</dt>
          <dd className="text-foreground">
            {gpus.length === 0 ? (
              '—'
            ) : (
              <ul className="list-disc pl-5">
                {gpus.map((g, i) => (
                  <li key={i}>{formatGpu(g)}</li>
                ))}
              </ul>
            )}
          </dd>
        </div>
        {sysinfo?.apple_silicon ? (
          <div className="col-span-1 flex justify-between gap-2 sm:col-span-2">
            <dt className="text-muted-foreground">Apple Silicon</dt>
            <dd className="text-foreground">yes</dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-4 flex items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => void onRedetect()}
          disabled={busy}
          data-testid="system-redetect"
        >
          {busy ? 'Re-detecting…' : 'Re-detect'}
        </Button>
        {redetectErr ? <span className="text-xs text-destructive">{redetectErr}</span> : null}
      </div>

      {gpus.length === 0 ? <GpuEnableCard /> : null}
    </div>
  )
}
