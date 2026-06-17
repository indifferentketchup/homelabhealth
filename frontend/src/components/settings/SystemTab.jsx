import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import {
  getSystemProfile,
  postSystemRedetect,
  putSystemProfile,
} from '@/api/system.js'
import { Button } from '@/components/ui/button'
import { TIERS, VISIBLE_TIERS } from './system/tierData.js'
import { HardwareCard } from './system/HardwareCard.jsx'
import { RecommendedBadge } from './system/RecommendedBadge.jsx'
import { TierRadio } from './system/TierRadio.jsx'
import { ModelsPanel } from './system/ModelsPanel.jsx'
import { PreFlightCard } from './system/PreFlightCard.jsx'


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

      {profile.retrieval_rebuilding ? (
        <div
          className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-300"
          data-testid="retrieval-rebuilding-banner"
        >
          Retrieval is rebuilding after a model change. Search results may be incomplete until it finishes.
        </div>
      ) : null}

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
        const tierMeta = TIERS.find((t) => t.id === recommended)
        return hasGpu && tierMeta?.isCpu() ? (
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
