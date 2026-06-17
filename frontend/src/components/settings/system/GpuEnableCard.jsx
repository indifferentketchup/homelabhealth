import { useCallback, useState } from 'react'
import { Button } from '@/components/ui/button'

const GPU_ENABLE_RAW = 'https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/enable-gpu.sh'
const GPU_ENABLE_BLOB = 'https://github.com/indifferentketchup/homelabhealth/blob/main/enable-gpu.sh'
const GPU_ENABLE_CMD = `curl -fsSL ${GPU_ENABLE_RAW} | sudo bash`

// Shown in the hardware card when no GPU is detected. The script runs on the
// HOST (the app's container can't install host packages / reconfigure Docker),
// so we surface the command + let the user read the exact file it will run.
export function GpuEnableCard() {
  const [copied, setCopied] = useState(false)
  const [open, setOpen] = useState(false)
  const [script, setScript] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  const copyCmd = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(GPU_ENABLE_CMD)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      setErr('Copy failed  -  select the command and copy it manually.')
    }
  }, [])

  const toggleScript = useCallback(async () => {
    const next = !open
    setOpen(next)
    if (next && script == null && !loading) {
      setLoading(true)
      setErr(null)
      try {
        const r = await fetch(GPU_ENABLE_RAW)
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        setScript(await r.text())
      } catch {
        setErr('Could not load the script here  -  use "View on GitHub" to read it.')
      } finally {
        setLoading(false)
      }
    }
  }, [open, script, loading])

  return (
    <div className="mt-4 rounded-lg border border-border bg-muted/30 p-3" data-testid="gpu-enable-card">
      <h4 className="text-sm font-medium text-foreground">Enable GPU acceleration</h4>
      <p className="mt-1 text-xs text-muted-foreground">
        Have an NVIDIA GPU? Docker can't pass it to the app yet. Run this once on the host,
        then pick a GPU tier below for inference to use it.
      </p>
      <div className="mt-2 flex items-stretch gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs text-foreground">
          {GPU_ENABLE_CMD}
        </code>
        <Button type="button" size="sm" variant="outline" className="shrink-0" onClick={() => void copyCmd()}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
      </div>
      <div className="mt-2 flex items-center gap-3">
        <button
          type="button"
          onClick={() => void toggleScript()}
          className="text-xs text-primary underline underline-offset-2 hover:no-underline"
          aria-expanded={open}
        >
          {open ? 'Hide script' : 'View script'}
        </button>
        <a
          href={GPU_ENABLE_BLOB}
          target="_blank"
          rel="noreferrer noopener"
          className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
        >
          View on GitHub ↗
        </a>
      </div>
      {err ? <p className="mt-2 text-xs text-destructive">{err}</p> : null}
      {open ? (
        <div className="mt-2">
          {loading ? (
            <p className="text-xs text-muted-foreground">Loading…</p>
          ) : !err && script != null ? (
            <pre className="max-h-72 overflow-auto rounded-md border border-border bg-background p-2 text-[11px] leading-relaxed text-foreground">
              <code>{script}</code>
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
