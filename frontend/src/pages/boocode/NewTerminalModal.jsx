import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2, ServerCog } from 'lucide-react'

import * as terminalsApi from '@/api/terminals.js'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

export default function NewTerminalModal({ dawId, onClose, onCreated, onError }) {
  const [machineId, setMachineId] = useState(null)
  const [label, setLabel] = useState('')
  const [startingCmd, setStartingCmd] = useState('')
  const [attachToDaw, setAttachToDaw] = useState(Boolean(dawId))
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState(null)

  const { data: machines, isLoading } = useQuery({
    queryKey: ['terminal-machines'],
    queryFn: () => terminalsApi.listMachines(),
    staleTime: 60_000,
  })

  const enabledMachines = useMemo(
    () => (Array.isArray(machines) ? machines.filter((m) => m.enabled) : []),
    [machines],
  )

  useEffect(() => {
    if (!machineId && enabledMachines.length > 0) {
      const local = enabledMachines.find((m) => m.name === 'local')
      setMachineId(local ? local.id : enabledMachines[0].id)
    }
  }, [enabledMachines, machineId])

  const submit = async () => {
    setErr(null)
    if (!machineId) {
      setErr('Pick a machine.')
      return
    }
    setSubmitting(true)
    try {
      const created = await terminalsApi.create({
        machineId,
        dawId: attachToDaw ? dawId : null,
        label: label.trim() || null,
        startingCmd: startingCmd.trim() || null,
      })
      onCreated?.(created)
    } catch (e) {
      let msg = e?.message || 'Could not create session'
      try {
        const parsed = JSON.parse(msg)
        if (parsed?.detail) msg = String(parsed.detail)
      } catch {
        /* message wasn't JSON; use as-is */
      }
      setErr(msg)
      if (typeof onError === 'function') onError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose?.() }}>
      <DialogContent
        className="sm:max-w-lg"
        style={{
          background: 'var(--bg-panel)',
          borderColor: 'color-mix(in srgb, var(--orange, #ff8c00) 40%, transparent)',
          boxShadow: 'var(--glow-orange)',
        }}
      >
        <DialogHeader>
          <DialogTitle
            style={{
              fontFamily: "'Orbitron', sans-serif",
              letterSpacing: '0.2em',
              color: 'var(--orange, #ff8c00)',
            }}
          >
            NEW TERMINAL
          </DialogTitle>
        </DialogHeader>

        <div
          className="flex flex-col gap-4 py-2"
          style={{ fontFamily: "'JetBrains Mono', monospace" }}
        >
          <div className="flex flex-col gap-1.5">
            <Label>Machine</Label>
            {isLoading ? (
              <div
                className="flex items-center gap-2 px-1 text-xs"
                style={{ color: 'var(--text-dim)' }}
              >
                <Loader2 className="size-3 animate-spin" />
                Loading…
              </div>
            ) : enabledMachines.length === 0 ? (
              <div
                className="rounded border px-3 py-2 text-xs"
                style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}
              >
                No machines enabled.
              </div>
            ) : (
              <div className="grid gap-1.5">
                {enabledMachines.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setMachineId(m.id)}
                    className="flex items-start gap-2 rounded border px-2.5 py-2 text-left transition-colors"
                    style={{
                      borderColor:
                        machineId === m.id ? 'var(--orange, #ff8c00)' : 'var(--border)',
                      background: machineId === m.id ? 'var(--bg-card)' : 'transparent',
                    }}
                  >
                    <ServerCog
                      className="size-4 shrink-0"
                      style={{
                        color:
                          machineId === m.id ? 'var(--orange, #ff8c00)' : 'var(--text-dim)',
                      }}
                    />
                    <div className="min-w-0 flex-1">
                      <div
                        className="text-xs font-medium tracking-wide"
                        style={{
                          color: machineId === m.id ? 'var(--orange, #ff8c00)' : 'var(--text)',
                        }}
                      >
                        {m.name}
                      </div>
                      <div
                        className="truncate text-[0.6875rem]"
                        style={{ color: 'var(--text-dim)' }}
                      >
                        {m.ssh_user ? `${m.ssh_user}@${m.host}` : m.host}
                        {m.default_cwd ? ` · ${m.default_cwd}` : ''}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bc-term-label">Label (optional)</Label>
            <Input
              id="bc-term-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. llama-swap"
              maxLength={120}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bc-term-cmd">Starting command (optional)</Label>
            <Textarea
              id="bc-term-cmd"
              value={startingCmd}
              onChange={(e) => setStartingCmd(e.target.value)}
              placeholder="e.g. cd /opt/boolab && git status"
              rows={2}
            />
          </div>

          {dawId ? (
            <label
              className="flex items-center gap-2 text-xs"
              style={{ color: 'var(--text)' }}
            >
              <input
                type="checkbox"
                checked={attachToDaw}
                onChange={(e) => setAttachToDaw(e.target.checked)}
              />
              <span>Attach to current DAW</span>
            </label>
          ) : null}

          {err ? (
            <div
              className="rounded-md border px-3 py-2 text-xs"
              style={{ borderColor: '#ff6b6b', color: '#ff6b6b', background: 'transparent' }}
            >
              {err}
            </div>
          ) : null}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            onClick={submit}
            disabled={submitting || !machineId || enabledMachines.length === 0}
            style={{
              borderColor: 'var(--orange, #ff8c00)',
              color: 'var(--orange, #ff8c00)',
              background: 'var(--bg-card)',
              fontFamily: "'Orbitron', sans-serif",
              letterSpacing: '0.2em',
            }}
          >
            {submitting ? 'STARTING…' : 'START'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
