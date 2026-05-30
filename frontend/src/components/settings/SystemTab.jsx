import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getDoctor,
  getSystemProfile,
  postSystemRedetect,
  putSystemProfile,
} from '@/api/system.js'
import {
  cancelPull,
  listModels,
  pullModel,
} from '@/api/models.js'
import { listProviders, testProvider } from '@/api/providers.js'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const ROLE_DISPLAY = {
  chat:         { label: 'Chat',      desc: 'Answers your questions using health context' },
  tasks:        { label: 'Tasks',     desc: 'Handles background jobs like summarization' },
  embed:        { label: 'Search',    desc: 'Converts text into vectors so documents can be found' },
  rerank:       { label: 'Relevance', desc: 'Re-scores search results for accuracy' },
  vision:       { label: 'Vision',    desc: 'Understands medical images for chat' },
  vision_embed: { label: 'Vision Search', desc: 'Converts medical images into searchable vectors' },
}

function RoleCell({ role }) {
  const display = ROLE_DISPLAY[role]
  if (!display) return <span className="font-medium text-foreground">{role}</span>
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="font-medium text-foreground cursor-default border-b border-dotted border-muted-foreground/30">
          {display.label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p className="text-xs">{display.desc}</p>
        <p className="font-mono text-[10px] text-muted-foreground mt-0.5">{role}</p>
      </TooltipContent>
    </Tooltip>
  )
}

/**
 * Per-tier metadata for the picker.
 *
 * Phase 0 source: hlh_phase0_design.md §Tier definitions (sysinfo + UX).
 * Phase 1 update (hlh_phase1_design.md §Tier model defaults): chat strings
 * now reflect MedGemma defaults for cpu-std and up. Footprints are rough.
 */
const TIERS = [
  {
    id: 'cpu-min',
    label: 'CPU — minimal',
    chat: 'Qwen3.5 0.8B Q8_0',
    embed: 'bge-m3 (1024-dim)',
    rerank: 'bge-reranker-v2-m3',
    vision: '— (not available)',
    visionSearch: '— (not enough RAM)',
    footprint: '~1.5 GB RAM peak · ~0.9 GB disk · 8K context',
    diskGb: 1,
    detect: '<16 GB RAM, no GPU',
  },
  {
    id: 'cpu-std',
    label: 'CPU — standard',
    chat: 'MedGemma 1.5 4B Q4_K_M',
    embed: 'bge-large-en-v1.5 Q8',
    rerank: 'bge-reranker-base (CPU)',
    vision: 'MedGemma 1.5 4B (mmproj)',
    visionSearch: '— (not enough RAM)',
    footprint: '~4 GB RAM peak · ~2.8 GB disk · 8K context',
    diskGb: 3,
    detect: '≥16 GB RAM, no GPU',
  },
  {
    id: 'gpu-4gb',
    label: 'GPU — 4 GB class',
    chat: 'MedGemma 1.5 4B Q4_K_M',
    embed: 'bge-m3 (1024-dim)',
    rerank: 'bge-reranker-v2-m3',
    vision: 'MedGemma 1.5 4B (mmproj)',
    visionSearch: '— (not enough VRAM)',
    footprint: '~3.5 GB VRAM peak · ~2.8 GB disk · 32K context',
    diskGb: 3,
    detect: '4–5 GB VRAM',
  },
  {
    id: 'gpu-8gb',
    label: 'GPU — 8 GB class',
    chat: 'MedGemma 1.5 4B Q8_0',
    embed: 'bge-large-en-v1.5 FP16',
    rerank: 'bge-reranker-v2-m3',
    vision: 'MedGemma 1.5 4B (mmproj)',
    visionSearch: 'MedSigLIP (opt-in, vision profile)',
    footprint: '~6 GB VRAM peak · ~4.5 GB disk · 32K context',
    diskGb: 5,
    detect: '6–11 GB VRAM',
  },
  {
    id: 'gpu-16gb',
    label: 'GPU — 16 GB class',
    chat: 'MedGemma 27B Q4_K_M',
    embed: 'Harrier-0.6B Q8',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 27B (mmproj)',
    visionSearch: 'MedSigLIP (opt-in, vision profile)',
    footprint: '~16 GB VRAM peak · ~16 GB disk · 32K context',
    diskGb: 16,
    detect: '12–23 GB VRAM',
  },
  {
    id: 'gpu-24gb+',
    label: 'GPU — 24 GB+',
    chat: 'MedGemma 27B Q4_K_M',
    embed: 'Harrier-0.6B Q8',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'MedGemma 27B (mmproj)',
    visionSearch: 'MedSigLIP (opt-in, vision profile)',
    footprint: '~18 GB VRAM peak · ~18 GB disk · 64K context',
    diskGb: 18,
    detect: '≥24 GB VRAM',
  },
  {
    id: 'apple-mlx',
    label: 'Apple Silicon (MLX) — deferred to Phase 6',
    chat: 'MedGemma 4B MLX',
    embed: 'bge-large-en-v1.5 MLX',
    rerank: 'bge-reranker-v2-m3 MLX',
    vision: 'Qwen2.5-VL MLX',
    visionSearch: '—',
    footprint: '~12–16 GB unified · varies',
    diskGb: 12,
    detect: 'Apple Silicon, ≥16 GB unified',
  },
  {
    id: 'external',
    label: 'External providers only',
    chat: '—',
    embed: '—',
    rerank: '—',
    vision: '—',
    visionSearch: '—',
    footprint: 'No local model footprint',
    diskGb: 0,
    detect: 'Operator chose external only',
  },
]

const VISIBLE_TIERS = TIERS.filter((t) => t.id !== 'external')


function formatGpu(g) {
  if (!g || typeof g !== 'object') return null
  const name = (typeof g.name === 'string' && g.name.trim()) || 'GPU'
  const mb = Number(g.memory_total_mb)
  if (!Number.isFinite(mb) || mb <= 0) return name
  const gb = Math.round((mb / 1024) * 10) / 10
  return `${name} (${gb} GB)`
}


function rationaleFor(sysinfo, recommended) {
  if (!sysinfo || typeof sysinfo !== 'object') {
    return 'no hardware detected yet — click Re-detect'
  }
  const gpus = Array.isArray(sysinfo.gpus) ? sysinfo.gpus : []
  const maxVramMb = gpus.length
    ? Math.max(0, ...gpus.map((g) => Number(g?.memory_total_mb) || 0))
    : 0
  const maxVramGb = Math.floor(maxVramMb / 1024)
  const ram = Number(sysinfo.ram_total_gb) || 0
  const apple = !!sysinfo.apple_silicon
  switch (recommended) {
    case 'gpu-24gb+':
      return `${maxVramGb} GB VRAM detected → gpu-24gb+`
    case 'gpu-16gb':
      return `${maxVramGb} GB VRAM detected → gpu-16gb`
    case 'gpu-8gb':
      return `${maxVramGb} GB VRAM detected → gpu-8gb`
    case 'gpu-4gb':
      return `${maxVramGb} GB VRAM detected → gpu-4gb (partial offload)`
    case 'apple-mlx':
      return `Apple Silicon, ${ram} GB unified memory → apple-mlx`
    case 'cpu-std':
      return `${ram} GB RAM, no usable GPU → cpu-std`
    case 'cpu-min':
    default:
      return apple
        ? `Apple Silicon, ${ram} GB unified (below 16 GB threshold) → cpu-min`
        : `${ram} GB RAM, no GPU → cpu-min`
  }
}


const GPU_ENABLE_RAW = 'https://raw.githubusercontent.com/indifferentketchup/homelabhealth/main/enable-gpu.sh'
const GPU_ENABLE_BLOB = 'https://github.com/indifferentketchup/homelabhealth/blob/main/enable-gpu.sh'
const GPU_ENABLE_CMD = `curl -fsSL ${GPU_ENABLE_RAW} | sudo bash`

// Shown in the hardware card when no GPU is detected. The script runs on the
// HOST (the app's container can't install host packages / reconfigure Docker),
// so we surface the command + let the user read the exact file it will run.
function GpuEnableCard() {
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
      setErr('Copy failed — select the command and copy it manually.')
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
        setErr('Could not load the script here — use “View on GitHub” to read it.')
      } finally {
        setLoading(false)
      }
    }
  }, [open, script, loading])

  return (
    <div className="mt-4 rounded-lg border border-border bg-muted/30 p-3" data-testid="gpu-enable-card">
      <h4 className="text-sm font-medium text-foreground">Enable GPU acceleration</h4>
      <p className="mt-1 text-xs text-muted-foreground">
        Have an NVIDIA GPU? Docker can’t pass it to the app yet. Run this once on the host,
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

function HardwareCard({ sysinfo, detectedAt, busy, onRedetect, redetectErr }) {
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


function RecommendedBadge({ recommended, sysinfo }) {
  const tierMeta = TIERS.find((t) => t.id === recommended)
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">Recommended tier</h3>
        <span
          className="inline-block rounded-full bg-primary/15 px-2.5 py-0.5 font-mono text-xs font-medium text-foreground"
          data-testid="system-recommended-tier"
        >
          {recommended || '—'}
        </span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {tierMeta ? tierMeta.label + ' — ' : ''}{rationaleFor(sysinfo, recommended)}
      </p>
    </div>
  )
}


function TierRadio({ tier, selected, onSelect, isRecommended, disabled }) {
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
        <div>Vision Search: <span className="text-foreground">{tier.visionSearch}</span></div>
      </div>
    </label>
  )
}


// ──────────────────────────────────────────────────────────────────────────────
// Phase 1: Models sub-section.
// Polls /api/models every 2s while any row is `pulling`; idle otherwise.
// Phase 2.B: Synthetic embed + rerank rows from bundled providers.
// ──────────────────────────────────────────────────────────────────────────────

const MAX_SYNTH_ATTEMPTS = 60
const SYNTH_POLL_MS = 5_000

function progressFraction(row) {
  const pulled = Number(row?.pulled_bytes) || 0
  const total = Number(row?.expected_bytes) || 0
  if (total <= 0 || pulled < 0) return null
  return Math.min(1, Math.max(0, pulled / total))
}

function formatBytes(n) {
  const v = Number(n)
  if (!Number.isFinite(v) || v <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let x = v
  let i = 0
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024
    i += 1
  }
  return `${x.toFixed(x >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}


function StatusBadge({ status }) {
  let cls = 'bg-muted text-muted-foreground'
  if (status === 'ready') cls = 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
  else if (status === 'pulling') cls = 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
  else if (status === 'failed') cls = 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
  else if (status === 'skipped') cls = 'bg-muted text-muted-foreground'
  else if (status === 'unavailable') cls = 'bg-muted text-muted-foreground'
  else if (status === 'inactive') cls = 'bg-muted text-muted-foreground'
  else if (status === 'loading') cls = 'bg-sky-500/15 text-sky-700 dark:text-sky-300'
  else if (status === 'error') cls = 'bg-rose-500/15 text-rose-700 dark:text-rose-300'
  return (
    <span className={cn('inline-block rounded px-1.5 py-0.5 font-mono text-[11px]', cls)}>
      {status || '—'}
    </span>
  )
}

/**
 * Derive the display state for a synthetic (embed/rerank) row.
 * @param {{ last_verified_status: string|null }} row
 * @param {number} attempts - number of poll attempts so far
 * @returns {{ state: 'ready'|'loading'|'error', msg: string }}
 */
const VISION_SEARCH_TIERS = new Set(['gpu-8gb', 'gpu-16gb', 'gpu-24gb+'])

function friendlyError(raw) {
  if (!raw) return null
  if (/ConnectError|Name or service not known|Connection refused/i.test(raw)) {
    return 'Service is starting up — it can take a few minutes to load the model. Try the Test button shortly.'
  }
  if (/timeout|timed out/i.test(raw)) return 'Service is taking a while to respond — the model may still be loading.'
  if (/HTTP 5\d\d/.test(raw)) return 'Service returned a server error. Check container logs for details.'
  return null
}

function syntheticStatus(row, attempts, currentTier) {
  if (row.role === 'vision_embed' && !VISION_SEARCH_TIERS.has(currentTier)) {
    return { state: 'unavailable', msg: 'Not available on this tier', rawMsg: '' }
  }
  const lvs = row.last_verified_status
  if (lvs && lvs.startsWith('ok')) return { state: 'ready', msg: '', rawMsg: '' }
  if (lvs && lvs.startsWith('inactive:')) {
    const reason = lvs.slice('inactive: '.length)
    return { state: 'inactive', msg: reason.charAt(0).toUpperCase() + reason.slice(1), rawMsg: '' }
  }
  if (lvs && lvs.startsWith('error:')) {
    const friendly = friendlyError(lvs)
    return { state: 'error', msg: friendly || lvs, rawMsg: friendly ? lvs : '' }
  }
  if ((attempts || 0) >= MAX_SYNTH_ATTEMPTS) {
    return { state: 'error', msg: "Sidecar didn't come up within 5 min. Check container logs.", rawMsg: '' }
  }
  return { state: 'loading', msg: '', rawMsg: '' }
}


function ModelsPanel({ currentTier }) {
  const queryClient = useQueryClient()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [actionErr, setActionErr] = useState(null)

  // ── Synthetic row polling state ──────────────────────────────────────────
  const [synthAttempts, setSynthAttempts] = useState({}) // { provider_id: attempt_count }

  const refresh = useCallback(async () => {
    try {
      const data = await listModels()
      const filtered = (data?.items ?? []).filter((r) => r.tier === currentTier)
      setItems(filtered)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load models')
    } finally {
      setLoading(false)
    }
  }, [currentTier])

  useEffect(() => {
    setLoading(true)
    void refresh()
  }, [refresh])

  const anyPulling = useMemo(() => items.some((r) => r.status === 'pulling'), [items])

  useEffect(() => {
    if (!anyPulling) return
    const t = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(t)
  }, [anyPulling, refresh])

  // ── Bundled providers query (for synthetic embed + rerank rows) ──────────
  const { data: providersData } = useQuery({
    queryKey: ['providers'],
    queryFn: () => listProviders(),
    staleTime: 30_000,
  })
  const providers = providersData?.items ?? []

  const SYNTH_ROLE_META = {
    embed: { model: 'BAAI/bge-m3', license: 'mit', license_url: 'https://huggingface.co/BAAI/bge-m3' },
    rerank: { model: 'BAAI/bge-reranker-v2-m3', license: 'apache-2.0', license_url: 'https://huggingface.co/BAAI/bge-reranker-v2-m3' },
    vision_embed: { model: 'google/medsiglip-448', license: 'apache-2.0', license_url: 'https://huggingface.co/google/medsiglip-448' },
  }

  // Roles that already have a real download row above (chat/embed/rerank/tasks/
  // vision). Since v1.1.4 gave embed/rerank actual download specs, their
  // synthetic provider rows became duplicates — drop those, keeping only roles
  // with no download row (vision_embed → the medsiglip sidecar).
  const downloadedRoles = useMemo(() => new Set(items.map((r) => r.role)), [items])

  const syntheticRows = useMemo(
    () =>
      providers
        .filter(
          (p) => p.is_bundled && SYNTH_ROLE_META[p.role] && !downloadedRoles.has(p.role),
        )
        .map((p) => ({
          id: p.id,
          role: p.role,
          model: SYNTH_ROLE_META[p.role].model,
          last_verified_status: p.last_verified_status,
          license: SYNTH_ROLE_META[p.role].license,
          license_url: SYNTH_ROLE_META[p.role].license_url,
        })),
    [providers, downloadedRoles],
  )

  // ── Polling for synthetic rows in "loading" state ────────────────────────
  useEffect(() => {
    const loadingRows = syntheticRows.filter(
      (r) => !r.last_verified_status || r.last_verified_status === '',
    )
    if (loadingRows.length === 0) return

    const interval = window.setInterval(async () => {
      for (const row of loadingRows) {
        const attempts = synthAttempts[row.id] || 0
        if (attempts >= MAX_SYNTH_ATTEMPTS) continue
        try {
          await testProvider(row.id)
        } catch {
          /* ignore — provider.last_verified_status is updated server-side */
        }
        setSynthAttempts((cur) => ({ ...cur, [row.id]: (cur[row.id] || 0) + 1 }))
      }
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    }, SYNTH_POLL_MS)

    return () => window.clearInterval(interval)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syntheticRows, queryClient])
  // Note: synthAttempts intentionally excluded from deps to avoid restarting
  // the interval on every count increment; reads the latest value via
  // setSynthAttempts functional updater instead.

  async function onTestSynthetic(row) {
    // Reset attempt counter so the 60-attempt cap starts fresh.
    setSynthAttempts((cur) => ({ ...cur, [row.id]: 0 }))
    setActionErr(null)
    try {
      await testProvider(row.id)
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : 'Test failed')
    }
  }

  async function onPull(row) {
    setActionErr(null)
    try {
      await pullModel(row.id)
      // Optimistically mark pulling so polling kicks in immediately.
      setItems((cur) => cur.map((r) => (r.id === row.id ? { ...r, status: 'pulling' } : r)))
      await refresh()
    } catch (e) {
      const raw = e instanceof Error ? e.message : 'Pull failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch {
        /* not JSON */
      }
      setActionErr(pretty)
    }
  }

  // Pull all pending rows in sequence. The puller serializes via _PULL_LOCK
  // server-side anyway, so firing them one-by-one with awaits keeps the UI
  // honest about which row is "in flight" right now.
  const pendingRows = useMemo(
    () => items.filter((r) => r.status === 'pending' || r.status === 'failed'),
    [items],
  )
  const [pullingAll, setPullingAll] = useState(false)
  async function onPullAll() {
    if (pullingAll || pendingRows.length === 0) return
    setPullingAll(true)
    setActionErr(null)
    try {
      for (const row of pendingRows) {
        try {
          await pullModel(row.id)
          setItems((cur) => cur.map((r) => (r.id === row.id ? { ...r, status: 'pulling' } : r)))
        } catch (e) {
          const raw = e instanceof Error ? e.message : 'Pull failed'
          let pretty = raw
          try {
            const parsed = JSON.parse(raw)
            if (parsed?.detail) pretty = String(parsed.detail)
          } catch { /* not JSON */ }
          setActionErr(`${row.role}: ${pretty}`)
          // Continue to next row — one failure shouldn't block the rest.
        }
      }
      await refresh()
    } finally {
      setPullingAll(false)
    }
  }

  async function onCancel(row) {
    setActionErr(null)
    try {
      await cancelPull(row.id)
      await refresh()
    } catch (e) {
      setActionErr(e instanceof Error ? e.message : 'Cancel failed')
    }
  }

  return (
    <div className="space-y-2" data-testid="system-models-panel">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-medium text-foreground">Models for this tier</h3>
        <span className="text-xs text-muted-foreground">tier: <span className="font-mono">{currentTier || '—'}</span></span>
      </div>
      <p className="text-xs text-muted-foreground">
        Bundled-AI artifacts the operator downloads to the local cache. Polls every 2s while a pull
        is active. Gated rows (MedGemma) need an <span className="font-mono">HF_TOKEN</span> and a
        license click at the linked HF page.
      </p>
      <p className="text-xs text-muted-foreground">
        Embed, rerank, and vision embed weights are downloaded automatically by their
        sidecars on first boot. They appear as{' '}
        <span className="font-mono">loading</span> until the sidecar reports healthy, then{' '}
        <span className="font-mono">ready</span>. No Pull button — the sidecar manages itself.
      </p>

      {actionErr ? <p className="text-sm text-destructive">{actionErr}</p> : null}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {/* First-install / post-tier-change prompt. Surfaces whenever pending or
          failed rows exist; one click queues them all (serialized server-side
          via _PULL_LOCK in model_puller). */}
      {!loading && pendingRows.length > 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-primary/40 bg-primary/5 p-3">
          <div className="text-sm">
            <span className="font-medium text-foreground">
              {pendingRows.length} model{pendingRows.length === 1 ? '' : 's'} ready to download
            </span>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Sequential downloads — watch the per-row progress bar below.
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            onClick={() => void onPullAll()}
            disabled={pullingAll || anyPulling}
            data-testid="system-models-pull-all"
          >
            {pullingAll ? 'Queuing…' : 'Pull all'}
          </Button>
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading models…</p>
      ) : items.length === 0 && syntheticRows.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No bundled artifacts for this tier (or you picked <span className="font-mono">external</span>).
        </p>
      ) : (
        <TooltipProvider>
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full table-auto text-sm">
            <thead className="bg-muted/40 text-left text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Role</th>
                <th className="px-3 py-2 font-medium">Model</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Progress</th>
                <th className="px-3 py-2 font-medium">License</th>
                <th className="px-3 py-2 font-medium text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {/* Puller-driven chat rows */}
              {items.map((row) => {
                const frac = progressFraction(row)
                return (
                  <tr key={row.id} className="border-t border-border align-top">
                    <td className="px-3 py-2"><RoleCell role={row.role} /></td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground" title={row.model_id}>
                      <div>{row.repo}</div>
                      <div className="text-[11px]">{row.filename}{row.quant ? ` · ${row.quant}` : ''}</div>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={row.status} />
                      {row.error_message ? (
                        <div className="mt-1 text-xs text-destructive" data-testid={`system-model-error-${row.role}`}>
                          {row.error_message}
                          {/* Only surface the license link when the puller reported a
                              401-style license-acceptance error; otherwise the link is
                              misleading (a 404 means the file is missing, not gated). */}
                          {row.license_url && row.error_message.startsWith('License acceptance') ? (
                            <>
                              {' '}
                              <a
                                href={row.license_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="underline underline-offset-2 hover:text-foreground"
                              >
                                Visit and accept here.
                              </a>
                            </>
                          ) : null}
                        </div>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.status === 'pulling' || row.status === 'ready' ? (
                        <div className="flex flex-col gap-1">
                          <div className="h-1.5 w-32 overflow-hidden rounded-full bg-muted">
                            <div
                              className="h-full bg-primary transition-all"
                              style={{ width: `${Math.round(((frac ?? 0) * 100))}%` }}
                              data-testid={`system-model-progress-${row.role}`}
                            />
                          </div>
                          <span className="font-mono text-[11px] text-muted-foreground">
                            {formatBytes(row.pulled_bytes)} / {formatBytes(row.expected_bytes)}
                            {frac != null ? ` (${Math.round(frac * 100)}%)` : ''}
                          </span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.license ? (
                        <a
                          href={row.license_url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline underline-offset-2 hover:text-foreground"
                          title={row.license_url || ''}
                        >
                          {row.license}
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {row.status === 'pulling' ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void onCancel(row)}
                          data-testid={`system-model-cancel-${row.role}`}
                        >
                          Cancel
                        </Button>
                      ) : (
                        <Button
                          type="button"
                          size="sm"
                          onClick={() => void onPull(row)}
                          data-testid={`system-model-pull-${row.role}`}
                        >
                          {row.status === 'ready' ? 'Re-pull' : 'Pull'}
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}

              {/* Synthetic embed + rerank rows (Phase 2.B) */}
              {syntheticRows.map((row) => {
                const { state, msg, rawMsg } = syntheticStatus(row, synthAttempts[row.id], currentTier)
                return (
                  <tr
                    key={row.id}
                    className={cn('border-t border-border align-top', state === 'unavailable' && 'opacity-40')}
                    data-testid={`system-synth-row-${row.role}`}
                  >
                    <td className="px-3 py-2"><RoleCell role={row.role} /></td>
                    <td className="px-3 py-2 font-mono text-xs text-muted-foreground">
                      {row.model}
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={state} />
                      {state === 'unavailable' && msg ? (
                        <div className="mt-1 text-xs text-muted-foreground">{msg}</div>
                      ) : state === 'inactive' && msg ? (
                        <div className="mt-1 text-xs text-muted-foreground">{msg}</div>
                      ) : state === 'error' && msg ? (
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <div
                              className="mt-1 text-xs text-destructive cursor-default"
                              data-testid={`system-synth-error-${row.role}`}
                            >
                              {msg}
                            </div>
                          </TooltipTrigger>
                          {rawMsg ? (
                            <TooltipContent side="bottom" className="max-w-sm">
                              <p className="font-mono text-[11px] break-all">{rawMsg}</p>
                            </TooltipContent>
                          ) : null}
                        </Tooltip>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {state === 'loading' ? (
                        <span
                          className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent text-sky-600"
                          aria-label="loading"
                        />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs">
                      {row.license ? (
                        <a
                          href={row.license_url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="underline underline-offset-2 hover:text-foreground"
                          title={row.license_url || ''}
                        >
                          {row.license}
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <div className="flex flex-col items-end gap-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => void onTestSynthetic(row)}
                          data-testid={`system-synth-test-${row.role}`}
                        >
                          Test
                        </Button>
                        <span className="text-[11px] text-muted-foreground">sidecar-managed</span>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        </TooltipProvider>
      )}
    </div>
  )
}


// ──────────────────────────────────────────────────────────────────────────────
// PreFlightCard — fetches /api/system/doctor on mount + has a refresh button.
// ──────────────────────────────────────────────────────────────────────────────

function PreFlightCard() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await getDoctor()
      setData(r)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load pre-flight')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const summary = data?.summary || { ok: 0, warn: 0, error: 0 }

  return (
    <details className="rounded-lg border border-border bg-card p-4" data-testid="preflight-card">
      <summary className="cursor-pointer text-sm font-medium text-foreground">
        Pre-flight checks
        {data ? (
          <span className="ml-2 font-mono text-xs text-muted-foreground">
            {summary.ok} ok · {summary.warn} warn · {summary.error} error
          </span>
        ) : null}
      </summary>
      <div className="mt-3 space-y-1.5">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          (data?.checks ?? []).map((c) => (
            <div key={c.name} className="flex items-start gap-2 text-sm">
              <span className={cn('font-mono',
                c.status === 'ok' && 'text-primary',
                c.status === 'warn' && 'text-secondary',
                c.status === 'error' && 'text-destructive',
              )}>
                {c.status === 'ok' ? '✓' : c.status === 'warn' ? '⚠' : '✗'}
              </span>
              <span className="font-mono text-xs text-foreground">{c.name}</span>
              <span className="text-xs text-muted-foreground">{c.detail}</span>
            </div>
          ))
        )}
        <div className="pt-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void refresh()}
            disabled={loading}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </Button>
        </div>
      </div>
    </details>
  )
}


// ──────────────────────────────────────────────────────────────────────────────
// SystemTab
// ──────────────────────────────────────────────────────────────────────────────


export default function SystemTab() {
  const queryClient = useQueryClient()
  const [loading, setLoading] = useState(true)
  const [loadErr, setLoadErr] = useState(null)
  const [profile, setProfile] = useState(null)
  const [selectedTier, setSelectedTier] = useState('')
  const [busy, setBusy] = useState(false)
  const [redetectErr, setRedetectErr] = useState(null)
  const [saveErr, setSaveErr] = useState(null)
  const [saveMsg, setSaveMsg] = useState(null)

  // Keep the local component state and the queryClient cache (used by
  // RequireSetup with the same queryKey) in lockstep. After save the gate
  // must see setup_complete=true immediately, or it will redirect back to
  // /settings the moment the user navigates away.
  function syncCache(updated) {
    queryClient.setQueryData(['system', 'profile'], updated)
  }

  async function refresh() {
    setLoadErr(null)
    try {
      const data = await getSystemProfile()
      setProfile(data)
      syncCache(data)
      if (data?.setup_complete) {
        setSelectedTier(data.tier || data.recommended_tier || '')
      } else {
        setSelectedTier(data.recommended_tier || data.tier || '')
      }
    } catch (e) {
      setLoadErr(e instanceof Error ? e.message : 'Failed to load system profile')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    ;(async () => {
      if (cancelled) return
      await refresh()
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function onRedetect() {
    setRedetectErr(null)
    setBusy(true)
    try {
      const updated = await postSystemRedetect()
      setProfile(updated)
      syncCache(updated)
      if (!updated?.setup_complete && (!selectedTier || selectedTier === profile?.recommended_tier)) {
        setSelectedTier(updated.recommended_tier || '')
      }
    } catch (e) {
      setRedetectErr(e instanceof Error ? e.message : 'Re-detect failed')
    } finally {
      setBusy(false)
    }
  }

  async function onSave() {
    if (!selectedTier) {
      setSaveErr('Pick a tier first.')
      return
    }
    setSaveErr(null)
    setSaveMsg(null)
    setBusy(true)
    try {
      const updated = await putSystemProfile({
        tier: selectedTier,
        tier_source: 'manual',
      })
      setProfile(updated)
      syncCache(updated)
      setSaveMsg('System tier saved.')
    } catch (e) {
      const raw = e instanceof Error ? e.message : 'Save failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch {
        /* not JSON */
      }
      setSaveErr(pretty)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (!saveMsg) return
    const t = window.setTimeout(() => setSaveMsg(null), 5000)
    return () => window.clearTimeout(t)
  }, [saveMsg])

  const saveEnabled = useMemo(() => {
    if (!profile || !selectedTier) return false
    if (!profile.setup_complete) return true
    return selectedTier !== profile.tier
  }, [profile, selectedTier])

  if (loading) {
    return (
      <section className="mx-auto w-full max-w-3xl">
        <p className="text-sm text-muted-foreground">Loading system settings…</p>
      </section>
    )
  }

  if (loadErr || !profile) {
    return (
      <section className="mx-auto w-full max-w-3xl space-y-2">
        <p className="text-sm text-destructive">{loadErr || 'Could not load system profile.'}</p>
      </section>
    )
  }

  return (
    <section className="mx-auto w-full max-w-3xl space-y-5">
      <div>
        <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">System</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Hardware-aware tier picker for the bundled AI stack. Pick the tier that matches your hardware — you can change
          it later.{' '}
          {profile.setup_complete ? null : (
            <span className="font-medium text-foreground" data-testid="system-first-boot-hint">
              First-time setup: please confirm a tier to continue.
            </span>
          )}
        </p>
      </div>

      <HardwareCard
        sysinfo={profile.sysinfo_json}
        detectedAt={profile.detected_at}
        busy={busy}
        onRedetect={onRedetect}
        redetectErr={redetectErr}
      />

      <RecommendedBadge
        recommended={profile.recommended_tier}
        sysinfo={profile.sysinfo_json}
      />

      {/* Step 3: GPU detected but <4 GB VRAM — falling back to CPU tier */}
      {(() => {
        const gpus = Array.isArray(profile.sysinfo_json?.gpus) ? profile.sysinfo_json.gpus : []
        const maxVramMb = Math.max(0, ...gpus.map(g => Number(g?.memory_total_mb) || 0))
        const hasGpu = gpus.length > 0 && maxVramMb > 0
        const recommended = profile.recommended_tier
        const isCpuTier = recommended === 'cpu-min' || recommended === 'cpu-std'
        return hasGpu && isCpuTier ? (
          <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
            <p className="text-sm text-blue-700 dark:text-blue-400">
              A GPU was detected but has less than 4 GB VRAM, which isn&apos;t enough for GPU-accelerated
              inference. HomeLab Health will run on CPU instead. The AI features still work — just slower.
            </p>
          </div>
        ) : null
      })()}

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">Choose a tier</h3>
        <div className="grid grid-cols-1 gap-2">
          {VISIBLE_TIERS.map((t) => (
            <TierRadio
              key={t.id}
              tier={t}
              selected={selectedTier}
              onSelect={setSelectedTier}
              isRecommended={t.id === profile.recommended_tier}
              disabled={busy}
            />
          ))}
        </div>
      </div>

      {/* Step 1: cpu-min amber warning */}
      {selectedTier === 'cpu-min' ? (
        <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
          <p className="text-sm text-yellow-700 dark:text-yellow-400">
            Minimal tier uses a small general-purpose model. Expect lower accuracy, higher hallucination
            risk, and no vision (image/PDF understanding). Upgrade to cpu-std or higher for medical-grade
            responses.
          </p>
        </div>
      ) : null}

      {/* Step 2: gpu-4gb info banner */}
      {selectedTier === 'gpu-4gb' ? (
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/5 p-4">
          <p className="text-sm text-blue-700 dark:text-blue-400">
            Your GPU has limited VRAM. HomeLab Health will use partial GPU offloading — some model layers
            run on GPU (faster) while others run on CPU. This is normal and works automatically.
          </p>
        </div>
      ) : null}

      {/* Disk space warning */}
      {(() => {
        const tierMeta = TIERS.find((t) => t.id === selectedTier)
        const diskFree = profile?.sysinfo_json?.disk_free_gb
        const needed = tierMeta?.diskGb || 0
        if (!needed || diskFree == null || diskFree >= needed + 5) return null
        return (
          <div className="rounded-lg border border-yellow-500/30 bg-yellow-500/5 p-4">
            <p className="text-sm text-yellow-700 dark:text-yellow-400">
              This tier needs ~{needed} GB plus headroom. You have {diskFree} GB free.
              The model download may fail. Free up space or pick a smaller tier.
            </p>
          </div>
        )
      })()}

      {/* Phase 1: Models sub-section — show bundled artifacts for the
          currently-selected tier (so the operator sees what would be pulled
          before they commit, and can drive pulls post-save). */}
      <ModelsPanel currentTier={selectedTier} />

      {saveErr ? (
        <p data-testid="system-save-error" className="text-sm text-destructive">
          {saveErr}
        </p>
      ) : null}
      {saveMsg ? <p className="text-sm text-foreground">{saveMsg}</p> : null}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <Button
          type="button"
          size="sm"
          onClick={() => void onSave()}
          disabled={busy || !saveEnabled}
          data-testid="system-save"
        >
          {busy ? 'Saving…' : 'Save tier'}
        </Button>
        <span className="text-xs text-muted-foreground">
          Currently: <span className="font-mono text-foreground">{profile.tier}</span>
          {' · '}
          source <span className="font-mono text-foreground">{profile.tier_source}</span>
          {' · '}
          setup{' '}
          <span className="font-mono text-foreground" data-testid="system-setup-complete">
            {profile.setup_complete ? 'complete' : 'pending'}
          </span>
        </span>
      </div>

      <PreFlightCard />
    </section>
  )
}
