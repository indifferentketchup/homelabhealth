import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import {
  getSystemProfile,
  postSystemRedetect,
  putSystemProfile,
} from '@/api/system.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/**
 * Per-tier metadata for the picker. Source of truth is
 * docs/hlh_phase0_design.md §Tier definitions. Footprints are rough
 * approximations (design says "approx VRAM/RAM, approx disk").
 */
const TIERS = [
  {
    id: 'cpu-min',
    label: 'CPU — minimal',
    chat: 'Qwen3 1.7B Q4',
    embed: 'bge-large-en-v1.5 Q4',
    rerank: 'flashrank',
    vision: '—',
    stt: 'whisper tiny',
    footprint: '~3 GB RAM peak · ~3 GB disk',
    detect: '<16 GB RAM, no GPU',
  },
  {
    id: 'cpu-std',
    label: 'CPU — standard',
    chat: 'Qwen3 4B Q4',
    embed: 'bge-large-en-v1.5 Q8',
    rerank: 'bge-reranker-base (CPU)',
    vision: '—',
    stt: 'whisper base',
    footprint: '~6 GB RAM peak · ~5 GB disk',
    detect: '≥16 GB RAM, no GPU',
  },
  {
    id: 'gpu-8gb',
    label: 'GPU — 8 GB class',
    chat: 'Qwen3 8B Q4',
    embed: 'bge-large-en-v1.5 FP16',
    rerank: 'bge-reranker-v2-m3',
    vision: '—',
    stt: 'whisper small',
    footprint: '~8 GB VRAM peak · ~10 GB disk',
    detect: '6–11 GB VRAM',
  },
  {
    id: 'gpu-16gb',
    label: 'GPU — 16 GB class',
    chat: 'Qwen3 14B Q4',
    embed: 'Harrier-0.6B Q8',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'Qwen2.5-VL-3B',
    stt: 'whisper medium',
    footprint: '~16 GB VRAM peak · ~20 GB disk',
    detect: '12–23 GB VRAM',
  },
  {
    id: 'gpu-24gb+',
    label: 'GPU — 24 GB+',
    chat: 'Qwen3 32B Q4',
    embed: 'Harrier-0.6B Q8',
    rerank: 'Qwen3-Reranker-0.6B',
    vision: 'Qwen2.5-VL-7B',
    stt: 'whisper large',
    footprint: '~26 GB VRAM peak · ~30 GB disk',
    detect: '≥24 GB VRAM',
  },
  {
    id: 'apple-mlx',
    label: 'Apple Silicon (MLX)',
    chat: 'Qwen3 MLX',
    embed: 'bge-large-en-v1.5 MLX',
    rerank: 'bge-reranker-v2-m3 MLX',
    vision: 'Qwen2.5-VL MLX',
    stt: 'whisper.cpp Metal',
    footprint: '~12–16 GB unified · ~15 GB disk',
    detect: 'Apple Silicon, ≥16 GB unified',
  },
  {
    id: 'external',
    label: 'External providers only',
    chat: '—',
    embed: '—',
    rerank: '—',
    vision: '—',
    stt: '—',
    footprint: 'No local model footprint',
    detect: 'Operator chose external only',
  },
]


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
        <div className="col-span-1 flex justify-between gap-2 sm:col-span-2">
          <dt className="text-muted-foreground">CPU model</dt>
          <dd className="truncate text-foreground" title={cpu}>{cpu}</dd>
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
        <div>STT: <span className="text-foreground">{tier.stt}</span></div>
      </div>
    </label>
  )
}


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
      // Initialize selection: if not set up, prefer the recommended tier;
      // otherwise reflect the saved tier so Save stays disabled until changed.
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
      // Don't overwrite user's selection. If they haven't completed setup yet
      // and weren't tracking a specific choice, nudge to the new recommendation.
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
    // First-boot: always allow Save (operator must confirm).
    if (!profile.setup_complete) return true
    // Already set up: only enable if user has changed their mind.
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

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">Choose a tier</h3>
        <div className="grid grid-cols-1 gap-2">
          {TIERS.map((t) => (
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
    </section>
  )
}
