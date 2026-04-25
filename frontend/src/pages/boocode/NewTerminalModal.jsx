import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, ServerCog } from 'lucide-react'

import { getDaw } from '@/api/daws.js'
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
  const [cwd, setCwd] = useState('')
  const [cwdDirty, setCwdDirty] = useState(false)
  const [attachToDaw, setAttachToDaw] = useState(Boolean(dawId))
  const [sessionType, setSessionType] = useState('bash')
  const [submitting, setSubmitting] = useState(false)
  const [submittedAt, setSubmittedAt] = useState(0)
  const [err, setErr] = useState(null)
  const [, forceTick] = useState(0)
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!submitting) return
    const t = setInterval(() => forceTick((n) => n + 1), 250)
    return () => clearInterval(t)
  }, [submitting])

  const { data: machines, isLoading } = useQuery({
    queryKey: ['terminal-machines'],
    queryFn: () => terminalsApi.listMachines(),
    staleTime: 60_000,
  })

  // Pull the DAW's repo_path so we can default machine + cwd when the user
  // opens this from inside a BooCode DAW.
  const { data: daw } = useQuery({
    queryKey: ['daw', dawId],
    queryFn: () => getDaw(dawId),
    enabled: Boolean(dawId),
    staleTime: 30_000,
  })

  const enabledMachines = useMemo(
    () => (Array.isArray(machines) ? machines.filter((m) => m.enabled) : []),
    [machines],
  )

  const dawRepoPath = attachToDaw ? (daw?.repo_path || '').trim() : ''
  const selectedMachine = useMemo(
    () => enabledMachines.find((m) => m.id === machineId) || null,
    [enabledMachines, machineId],
  )

  // Default machine: prefer ubuntu-homelab when we're attaching to a DAW
  // (repo files are bind-mounted into that agent), else first enabled.
  useEffect(() => {
    if (machineId || enabledMachines.length === 0) return
    const preferred = attachToDaw
      ? enabledMachines.find((m) => m.name === 'ubuntu-homelab')
      : null
    const fallback = enabledMachines.find((m) => m.name === 'ubuntu-homelab')
      || enabledMachines[0]
    setMachineId((preferred || fallback).id)
  }, [enabledMachines, machineId, attachToDaw])

  // Default cwd: DAW's repo_path if available, else the machine's default_cwd.
  // Users can override; once they edit the field we stop auto-updating it.
  useEffect(() => {
    if (cwdDirty) return
    const next = dawRepoPath || selectedMachine?.default_cwd || ''
    setCwd(next)
  }, [dawRepoPath, selectedMachine, cwdDirty])

  const computeAutoLabel = () => {
    if (!attachToDaw || !dawId) return null
    // Read the cached session list for this DAW; pick the next free integer.
    const cached = queryClient.getQueryData(['terminals', dawId])
    const active = Array.isArray(cached?.active) ? cached.active : []
    const recent = Array.isArray(cached?.recent) ? cached.recent : []
    const all = [...active, ...recent]
    const re = new RegExp(`^${sessionType}-(\\d+)$`)
    const used = new Set()
    for (const s of all) {
      const m = (s?.label || '').match(re)
      if (m) used.add(Number(m[1]))
    }
    let n = 1
    while (used.has(n)) n += 1
    return `${sessionType}-${n}`
  }

  const submit = async () => {
    setErr(null)
    if (!machineId) {
      setErr('Pick a machine.')
      return
    }
    setSubmitting(true)
    setSubmittedAt(Date.now())
    try {
      const trimmedCwd = cwd.trim()
      // Only send cwd when it diverges from the machine default — keeps
      // the legacy path (cwd=null → use machine.default_cwd) intact.
      const cwdOverride =
        trimmedCwd && trimmedCwd !== (selectedMachine?.default_cwd || '')
          ? trimmedCwd
          : null
      const created = await terminalsApi.create({
        machineId,
        dawId: attachToDaw ? dawId : null,
        label: label.trim() || computeAutoLabel(),
        startingCmd: startingCmd.trim() || null,
        cwd: cwdOverride,
        sessionType,
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

  const submitLabel = (() => {
    if (!submitting) return 'START'
    const elapsed = Date.now() - submittedAt
    if (elapsed >= 500 && sessionType !== 'bash') return 'CONNECTING…'
    return 'STARTING…'
  })()

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
            <Label>Type</Label>
            <div className="grid grid-cols-3 gap-1.5">
              {[
                { id: 'bash', name: 'Bash', desc: 'Interactive shell' },
                { id: 'claude', name: 'Claude Code', desc: 'Agentic CLI' },
                { id: 'opencode', name: 'OpenCode', desc: 'Agentic CLI' },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setSessionType(t.id)}
                  aria-pressed={sessionType === t.id}
                  className="flex flex-col items-start gap-0.5 rounded border px-2 py-2 text-left transition-colors"
                  style={{
                    borderColor: sessionType === t.id ? 'var(--orange, #ff8c00)' : 'var(--border)',
                    background: sessionType === t.id ? 'var(--bg-card)' : 'transparent',
                  }}
                >
                  <span
                    className="text-xs font-medium tracking-wide"
                    style={{
                      color: sessionType === t.id ? 'var(--orange, #ff8c00)' : 'var(--text)',
                    }}
                  >
                    {t.name}
                  </span>
                  <span className="text-[0.6875rem]" style={{ color: 'var(--text-dim)' }}>
                    {t.desc}
                  </span>
                </button>
              ))}
            </div>
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
            <Label htmlFor="bc-term-cwd">Working directory</Label>
            <Input
              id="bc-term-cwd"
              value={cwd}
              onChange={(e) => {
                setCwd(e.target.value)
                setCwdDirty(true)
              }}
              placeholder={selectedMachine?.default_cwd || '/'}
              maxLength={512}
            />
            {dawRepoPath && !cwdDirty ? (
              <span className="text-[0.6875rem]" style={{ color: 'var(--text-dim)' }}>
                Auto-filled from this DAW's repo path.
              </span>
            ) : null}
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
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
