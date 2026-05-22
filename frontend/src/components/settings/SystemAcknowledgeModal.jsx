import { useEffect, useState } from 'react'

import { getDoctor, postAcknowledge } from '@/api/system'
import { Button } from '@/components/ui/button'

export default function SystemAcknowledgeModal({ onAcknowledged }) {
  const [doctorData, setDoctorData] = useState(null)
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const d = await getDoctor()
        if (!cancelled) setDoctorData(d)
      } catch {
        if (!cancelled) setDoctorData({ checks: [] })  // tolerate failure; modal still shows
      }
    })()
    return () => { cancelled = true }
  }, [])

  const searchHealthy = (doctorData?.checks ?? []).some(
    (c) => c.name === 'hlh_search_reachable' && c.status === 'ok'
  )

  async function onContinue() {
    setBusy(true); setErr(null)
    try {
      await postAcknowledge()
      onAcknowledged()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Acknowledgement failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm" data-testid="ack-modal">
      <div className="max-w-lg rounded-lg border border-border bg-card p-6 shadow-lg">
        <h2 className="text-lg font-semibold text-foreground">
          HomeLab Health is a personal-records tool, not a medical service.
        </h2>
        <div className="mt-3 space-y-3 text-sm text-foreground">
          <div>
            <p className="font-medium">What it is:</p>
            <ul className="ml-5 list-disc space-y-0.5 text-muted-foreground">
              <li>A place to keep your records and notes</li>
              <li>A chat that can explain symptoms, conditions, and lab terms in plain language</li>
              {searchHealthy ? (
                <li>Optional web search to ground answers in current information</li>
              ) : null}
            </ul>
          </div>
          <div>
            <p className="font-medium">What it isn&apos;t:</p>
            <ul className="ml-5 list-disc space-y-0.5 text-muted-foreground">
              <li>A doctor. It doesn&apos;t diagnose. It will refuse.</li>
              <li>A pharmacist. It doesn&apos;t opine on drug interactions or dosages. It will refuse.</li>
              <li>A 911 alternative. If you&apos;re in crisis, it will show you the hotline.</li>
            </ul>
          </div>
          <p className="text-muted-foreground">
            By continuing, you acknowledge this is educational, not medical advice.
          </p>
        </div>
        <label className="mt-4 flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            className="size-4 accent-primary"
            data-testid="ack-checkbox"
          />
          I understand
        </label>
        {err ? <p className="mt-2 text-xs text-destructive">{err}</p> : null}
        <div className="mt-4 flex justify-end">
          <Button
            type="button"
            onClick={() => void onContinue()}
            disabled={!checked || busy}
            data-testid="ack-continue"
          >
            {busy ? 'Saving…' : 'Continue'}
          </Button>
        </div>
      </div>
    </div>
  )
}
