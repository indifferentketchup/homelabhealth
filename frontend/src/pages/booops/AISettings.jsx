import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getCustomInstructions, putCustomInstructions } from '@/api/customInstructions.js'
import { getGlobalSettings, getOllamaConfig, patchGlobalSettings, patchOllamaConfig } from '@/api/settings.js'
import { createDaw, deleteDaw, listDaws, updateDaw } from '@/api/daws.js'
import { extractMemory, getMemory, putMemory } from '@/api/memory.js'
import {
  createMemoryEntry,
  deleteMemoryEntry,
  listMemoryEntries,
  updateMemoryEntry,
} from '@/api/memoryEntries.js'
import {
  DEFAULT_OLLAMA_MODEL,
  deleteModel,
  fetchOllamaModels,
  getOllamaSettings,
  patchOllamaSettings,
  pullModel,
  unloadAllModels,
} from '@/api/ollama.js'
import { createPersona, deletePersona, listPersonas, updatePersona, uploadPersonaIcon } from '@/api/personas.js'
import { Button } from '@/components/ui/button'
import { cn, sortSelectedFirst } from '@/lib/utils'
import { useAppStore } from '@/store/index.js'

const MODE = 'booops'

function PersonaPickerButton({ label, value, personas, onChange, disabled }) {
  const btnRef = useRef(null)
  const wrapRef = useRef(null)
  const [open, setOpen] = useState(false)
  const [rect, setRect] = useState(null)

  const selected = useMemo(() => {
    if (!value) return null
    return personas.find((p) => p.id === value) ?? null
  }, [personas, value])

  useLayoutEffect(() => {
    if (!open || !btnRef.current) return
    const r = btnRef.current.getBoundingClientRect()
    setRect(r)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onDown(e) {
      if (wrapRef.current?.contains(e.target)) return
      setOpen(false)
    }
    function onKey(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const sorted = useMemo(() => sortSelectedFirst(personas, value, 'id'), [personas, value])

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="flex h-9 w-full items-center justify-between rounded-md border border-border bg-card px-3 text-left text-sm text-foreground outline-none ring-ring hover:bg-muted/50 focus-visible:ring-2 disabled:opacity-50"
      >
        <span className="flex min-w-0 items-center gap-2 truncate">
          {selected?.icon_url ? (
            <img src={selected.icon_url} alt="" className="size-6 shrink-0 rounded-full object-cover" />
          ) : selected ? (
            <span className="shrink-0" aria-hidden>
              {selected.avatar_emoji || '🤖'}
            </span>
          ) : null}
          <span className="truncate">{selected ? selected.name : label}</span>
        </span>
        <span className="text-muted-foreground" aria-hidden>
          ▾
        </span>
      </button>
      {open && rect && (
        <ul
          role="listbox"
          className="fixed z-[100] max-h-[min(50vh,16rem)] overflow-y-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-lg"
          style={{
            top: rect.bottom + 4,
            left: rect.left,
            minWidth: Math.max(rect.width, 220),
            maxWidth: 'min(100vw - 1rem, 24rem)',
          }}
        >
          <li role="option">
            <button
              type="button"
              className="flex w-full rounded-sm px-2 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
              onClick={() => {
                onChange(null)
                setOpen(false)
              }}
            >
              Default persona
            </button>
          </li>
          {sorted.map((p) => (
            <li key={p.id} role="option">
              <button
                type="button"
                className="flex w-full rounded-sm px-2 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  onChange(p.id)
                  setOpen(false)
                }}
              >
                {p.icon_url ? (
                  <img src={p.icon_url} alt="" className="mr-2 size-6 shrink-0 rounded-full object-cover" />
                ) : (
                  <span className="mr-2 shrink-0">{p.avatar_emoji || '🤖'}</span>
                )}
                <span className="truncate">{p.name}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const OLLAMA_SELECT_CLASS =
  'h-9 w-full rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2'

const CLAUDE_STORAGE_KEY_808 = '808notes_claude_enabled'

function parseSsePullBuffer(buffer) {
  const events = []
  let rest = buffer
  let idx
  while ((idx = rest.indexOf('\n\n')) >= 0) {
    const block = rest.slice(0, idx)
    rest = rest.slice(idx + 2)
    for (const line of block.split('\n')) {
      if (line.startsWith('data: ')) events.push(line.slice(6).trim())
    }
  }
  return { events, rest }
}

function OllamaDawModelsSection({ queryClient, selectClass, mode }) {
  const [pullName, setPullName] = useState('')
  const [pulling, setPulling] = useState(false)
  const [pullStatus, setPullStatus] = useState('')
  const [pullCompleted, setPullCompleted] = useState(null)
  const [pullTotal, setPullTotal] = useState(null)
  const [pullError, setPullError] = useState(null)
  const [pullCompleteMsg, setPullCompleteMsg] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState(false)
  const [toastMsg, setToastMsg] = useState(null)
  const [unloadPending, setUnloadPending] = useState(false)
  const [unloadSuccessMsg, setUnloadSuccessMsg] = useState(null)
  const [unloadErr, setUnloadErr] = useState(null)
  const pullAbortRef = useRef(null)

  const {
    data: ollamaData,
    isLoading: modelsLoading,
    isError: modelsError,
    refetch: refetchModels,
  } = useQuery({
    queryKey: ['ollama', 'models'],
    queryFn: fetchOllamaModels,
    staleTime: 60_000,
    retry: false,
  })

  const { data: ollamaSettings } = useQuery({
    queryKey: ['ollama', 'settings', mode],
    queryFn: () => getOllamaSettings(mode),
    staleTime: 30_000,
  })

  const modelEntries = useMemo(() => {
    const raw = Array.isArray(ollamaData?.models) ? ollamaData.models : []
    return raw
      .map((m) => ({
        name: typeof m?.name === 'string' ? m.name : '',
        parameterSize: m?.details?.parameter_size ?? null,
      }))
      .filter((m) => m.name)
  }, [ollamaData])

  const hiddenSet = useMemo(
    () => new Set(Array.isArray(ollamaSettings?.hidden_models) ? ollamaSettings.hidden_models : []),
    [ollamaSettings],
  )

  useEffect(() => {
    if (!toastMsg) return
    const t = window.setTimeout(() => setToastMsg(null), 2200)
    return () => window.clearTimeout(t)
  }, [toastMsg])

  useEffect(() => {
    if (pullCompleteMsg) {
      const t = window.setTimeout(() => {
        setPullCompleteMsg(false)
        setPullStatus('')
        setPullCompleted(null)
        setPullTotal(null)
      }, 3000)
      return () => window.clearTimeout(t)
    }
  }, [pullCompleteMsg])

  useEffect(
    () => () => {
      pullAbortRef.current?.abort()
    },
    [],
  )

  useEffect(() => {
    if (modelEntries.length === 0) {
      setDeleteTarget('')
      return
    }
    if (!deleteTarget || !modelEntries.some((m) => m.name === deleteTarget)) {
      setDeleteTarget(modelEntries[0].name)
    }
  }, [modelEntries, deleteTarget])

  async function onDefaultModelChange(value) {
    try {
      const out = await patchOllamaSettings({ default_model: value }, mode)
      queryClient.setQueryData(['ollama', 'settings', mode], out)
    } catch {
      /* ignore */
    }
  }

  async function setModelVisibility(name, visible) {
    const current = Array.isArray(ollamaSettings?.hidden_models) ? [...ollamaSettings.hidden_models] : []
    let next
    if (visible) {
      next = current.filter((h) => h !== name)
    } else if (!current.includes(name)) {
      next = [...current, name]
    } else {
      next = current
    }
    try {
      const out = await patchOllamaSettings({ hidden_models: next }, mode)
      queryClient.setQueryData(['ollama', 'settings', mode], out)
    } catch {
      /* ignore */
    }
  }

  async function onPullSubmit(e) {
    e.preventDefault()
    const model = pullName.trim()
    if (!model || pulling) return
    pullAbortRef.current?.abort()
    const ac = new AbortController()
    pullAbortRef.current = ac
    setPulling(true)
    setPullError(null)
    setPullCompleteMsg(false)
    setPullStatus('')
    setPullCompleted(null)
    setPullTotal(null)
    try {
      const res = await fetch(pullModel(model), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model }),
        signal: ac.signal,
      })
      if (!res.ok) {
        const t = await res.text().catch(() => '')
        throw new Error(t || res.statusText || String(res.status))
      }
      const reader = res.body?.getReader()
      if (!reader) throw new Error('No response body')
      const decoder = new TextDecoder()
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const { events, rest } = parseSsePullBuffer(buf)
        buf = rest
        for (const data of events) {
          if (data === '[DONE]') {
            setPullCompleteMsg(true)
            setPullStatus('✓ Pull complete')
            await refetchModels()
            await queryClient.invalidateQueries({ queryKey: ['ollama', 'settings', mode] })
            setPulling(false)
            pullAbortRef.current = null
            return
          }
          try {
            const obj = JSON.parse(data)
            if (obj.error) {
              setPullError(String(obj.error))
              setPulling(false)
              pullAbortRef.current = null
              return
            }
            if (obj.status != null) setPullStatus(String(obj.status))
            if (obj.completed != null && obj.total != null) {
              setPullCompleted(Number(obj.completed))
              setPullTotal(Number(obj.total))
            }
          } catch {
            /* ignore malformed */
          }
        }
      }
      if (buf.trim()) {
        const { events } = parseSsePullBuffer(`${buf}\n\n`)
        for (const data of events) {
          if (data === '[DONE]') {
            setPullCompleteMsg(true)
            setPullStatus('✓ Pull complete')
            await refetchModels()
            await queryClient.invalidateQueries({ queryKey: ['ollama', 'settings', mode] })
          }
        }
      }
    } catch (err) {
      if (err?.name === 'AbortError') {
        setPulling(false)
        pullAbortRef.current = null
        return
      }
      setPullError(err instanceof Error ? err.message : String(err))
    } finally {
      setPulling(false)
      pullAbortRef.current = null
    }
  }

  async function onUnloadAll() {
    if (unloadPending) return
    setUnloadSuccessMsg(null)
    setUnloadErr(null)
    setUnloadPending(true)
    try {
      const res = await unloadAllModels()
      const names = Array.isArray(res?.unloaded) ? res.unloaded : []
      if (names.length === 0) {
        setUnloadSuccessMsg('Nothing loaded')
      } else {
        setUnloadSuccessMsg(`Unloaded: ${names.join(', ')}`)
      }
      await refetchModels()
    } catch (e) {
      setUnloadErr(e instanceof Error ? e.message : String(e))
    } finally {
      setUnloadPending(false)
    }
  }

  async function onConfirmDelete() {
    const name = deleteTarget
    if (!name) return
    const wasDefault = ollamaSettings?.default_model === name
    const prevHidden = Array.isArray(ollamaSettings?.hidden_models) ? ollamaSettings.hidden_models : []
    const nextHidden = prevHidden.filter((h) => h !== name)
    try {
      await deleteModel(name)
      if (nextHidden.length !== prevHidden.length) {
        const out = await patchOllamaSettings({ hidden_models: nextHidden }, mode)
        queryClient.setQueryData(['ollama', 'settings', mode], out)
      }
      await refetchModels()
      const pack = await queryClient.fetchQuery({
        queryKey: ['ollama', 'models'],
        queryFn: fetchOllamaModels,
      })
      const raw = Array.isArray(pack?.models) ? pack.models : []
      const names = raw.map((m) => (typeof m?.name === 'string' ? m.name : '')).filter(Boolean)
      if (wasDefault) {
        const nextDef = names.find((n) => n === DEFAULT_OLLAMA_MODEL) ?? names[0] ?? ''
        const out = await patchOllamaSettings({ default_model: nextDef }, mode)
        queryClient.setQueryData(['ollama', 'settings', mode], out)
      }
      setDeleteConfirm(false)
      setDeleteTarget((prev) => (prev === name ? names[0] ?? '' : prev))
      setToastMsg('Model deleted')
    } catch (e) {
      setToastMsg(e instanceof Error ? e.message : 'Delete failed')
      setDeleteConfirm(false)
    }
  }

  const defaultModel = useMemo(() => {
    const api = String(ollamaSettings?.default_model ?? '').trim()
    const prefer = api || DEFAULT_OLLAMA_MODEL
    if (modelEntries.some((m) => m.name === prefer)) return prefer
    const nine = modelEntries.find((m) => m.name === DEFAULT_OLLAMA_MODEL)
    if (nine) return nine.name
    return modelEntries[0]?.name ?? prefer
  }, [ollamaSettings?.default_model, modelEntries])
  const progressPct =
    pullTotal != null && pullTotal > 0 && pullCompleted != null
      ? Math.min(100, Math.round((pullCompleted / pullTotal) * 100))
      : null

  const dawAppLabel = mode === '808notes' ? '808notes' : 'BooOps'

  return (
    <section className="space-y-6">
      {toastMsg && (
        <div
          role="status"
          className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground"
        >
          {toastMsg}
        </div>
      )}

      <div>
        <h2 className="text-sm font-medium text-foreground">Models ({dawAppLabel})</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          One Ollama server for all DAWs. Switch BooOps or 808notes to set that DAW’s default model and which models
          appear in the picker.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">Default model</h3>
        {modelsError ? (
          <p className="text-sm text-muted-foreground">Ollama unavailable</p>
        ) : (
          <label className="flex flex-col gap-1 text-sm">
            <span className="sr-only">Choose default model</span>
            <select
              className={selectClass}
              disabled={modelsLoading || modelEntries.length === 0}
              value={defaultModel}
              onChange={(e) => void onDefaultModelChange(e.target.value)}
            >
              {modelEntries.length === 0 && !modelsLoading ? (
                <option value="">No models</option>
              ) : null}
              {modelEntries.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">Visible models</h3>
        {modelsError ? (
          <p className="text-sm text-muted-foreground">Ollama unavailable</p>
        ) : modelsLoading ? (
          <p className="text-sm text-muted-foreground">Loading models…</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {modelEntries.map((m) => {
              const visible = !hiddenSet.has(m.name)
              return (
                <li
                  key={m.name}
                  className={cn(
                    'flex items-center justify-between gap-3 rounded-md px-2 py-2',
                    visible && 'bg-accent/30',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <span className="text-sm font-medium text-foreground">{m.name}</span>
                    {m.parameterSize ? (
                      <span className="ml-2 text-xs text-muted-foreground">{m.parameterSize}</span>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={visible}
                    aria-label={visible ? `Hide ${m.name}` : `Show ${m.name}`}
                    onClick={() => void setModelVisibility(m.name, !visible)}
                    className="relative inline-flex h-6 w-10 shrink-0 rounded-full border border-border transition-colors"
                    style={{
                      backgroundColor: visible ? 'var(--primary)' : 'var(--muted)',
                    }}
                  >
                    <span
                      className={cn(
                        'pointer-events-none block size-5 translate-x-0.5 rounded-full shadow transition-transform',
                        visible && 'translate-x-[1.15rem]',
                      )}
                      style={{ backgroundColor: 'var(--background)' }}
                    />
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">Pull model</h3>
        <form onSubmit={(e) => void onPullSubmit(e)} className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Model name</span>
            <input
              value={pullName}
              onChange={(e) => setPullName(e.target.value)}
              disabled={pulling}
              placeholder="e.g. llama3.2:latest"
              className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
            />
          </label>
          <Button type="submit" size="sm" disabled={pulling || !pullName.trim()}>
            {pulling ? 'Pulling…' : 'Pull'}
          </Button>
        </form>
        {(pullStatus || pullError || progressPct != null) && (
          <div className="space-y-2 pt-1">
            {pullError ? (
              <p className="text-sm text-destructive">{pullError}</p>
            ) : (
              <p className="text-sm text-muted-foreground">{pullStatus}</p>
            )}
            {progressPct != null && !pullError ? (
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-primary transition-[width] duration-300"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">Delete model</h3>
        {modelsError ? (
          <p className="text-sm text-muted-foreground">Ollama unavailable</p>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Model</span>
                <select
                  className={selectClass}
                  disabled={modelsLoading || modelEntries.length === 0}
                  value={deleteTarget}
                  onChange={(e) => {
                    setDeleteTarget(e.target.value)
                    setDeleteConfirm(false)
                  }}
                >
                  {modelEntries.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.name}
                    </option>
                  ))}
                </select>
              </label>
              <Button
                type="button"
                variant="destructive"
                size="sm"
                disabled={!deleteTarget || modelsLoading}
                onClick={() => setDeleteConfirm(true)}
              >
                Delete
              </Button>
            </div>
            {deleteConfirm && deleteTarget ? (
              <div className="rounded-md border border-border bg-background/80 p-3 text-sm">
                <p className="text-foreground">
                  Delete {deleteTarget}? This cannot be undone.
                </p>
                <div className="mt-2 flex gap-2">
                  <Button type="button" size="sm" variant="destructive" onClick={() => void onConfirmDelete()}>
                    Confirm
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => setDeleteConfirm(false)}>
                    Cancel
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">VRAM</h3>
        <p className="text-sm text-muted-foreground">Unload all models from VRAM</p>
        <Button type="button" size="sm" disabled={unloadPending} onClick={() => void onUnloadAll()}>
          {unloadPending ? 'Unloading…' : 'Unload all'}
        </Button>
        {unloadErr ? (
          <p className="text-sm text-destructive" role="status">
            {unloadErr}
          </p>
        ) : unloadSuccessMsg ? (
          <p className="text-sm text-muted-foreground" role="status">
            {unloadSuccessMsg}
          </p>
        ) : null}
      </div>
    </section>
  )
}

function readClaude808Enabled() {
  try {
    return localStorage.getItem(CLAUDE_STORAGE_KEY_808) === 'true'
  } catch {
    return false
  }
}

function persistClaude808Toggle(on) {
  try {
    localStorage.setItem(CLAUDE_STORAGE_KEY_808, on ? 'true' : 'false')
    window.dispatchEvent(new CustomEvent('808notes-models'))
  } catch {
    /* ignore */
  }
}

function Claude808notesModelPrefs() {
  const [claudeOn, setClaudeOn] = useState(() => readClaude808Enabled())
  useEffect(() => {
    const fn = () => setClaudeOn(readClaude808Enabled())
    window.addEventListener('808notes-models', fn)
    return () => window.removeEventListener('808notes-models', fn)
  }, [])

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
      <h3 className="text-sm font-medium text-foreground">Claude (808notes only)</h3>
      <p className="text-sm text-muted-foreground">
        Show Claude models in the 808notes picker. Requires API key on the host.
      </p>
      <label className="flex cursor-pointer items-center gap-3 text-sm">
        <input
          type="checkbox"
          checked={claudeOn}
          onChange={(e) => setClaudeOn(e.target.checked)}
          className="size-4 rounded border-border accent-primary"
        />
        <span className="text-foreground">Enable Claude in model list</span>
      </label>
      <Button type="button" size="sm" onClick={() => persistClaude808Toggle(claudeOn)}>
        Save Claude preference
      </Button>
    </div>
  )
}

const OLLAMA_DAW_LS = 'ai-ollama-daw-mode'
/** @deprecated Pre-DAW labeling; keep so existing localStorage rows still migrate. */
const OLLAMA_DAW_LS_LEGACY = `ai-ollama-${'work' + 'space'}-mode`

function readAiOllamaDawMode() {
  try {
    const v =
      localStorage.getItem(OLLAMA_DAW_LS) ?? localStorage.getItem(OLLAMA_DAW_LS_LEGACY)
    if (v === '808notes' || v === 'booops') return v
  } catch {
    /* ignore */
  }
  return 'booops'
}

export default function AISettings() {
  const queryClient = useQueryClient()
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setActivePersonaId = useAppStore((s) => s.setActivePersonaId)
  const [tab, setTab] = useState('personas')
  const [ollamaDawMode, setOllamaDawModeState] = useState(readAiOllamaDawMode)

  const setOllamaDawMode = useCallback((m) => {
    setOllamaDawModeState(m)
    try {
      localStorage.setItem(OLLAMA_DAW_LS, m)
    } catch {
      /* ignore */
    }
  }, [])

  const { data: personaPack } = useQuery({
    queryKey: ['personas'],
    queryFn: () => listPersonas(),
    staleTime: 15_000,
  })
  const personas = personaPack?.items ?? []

  useEffect(() => {
    if (personaPack?.items) setPersonas(personaPack.items)
  }, [personaPack, setPersonas])

  const { data: memoryRow, isLoading: memLoading } = useQuery({
    queryKey: ['memory', MODE],
    queryFn: () => getMemory(MODE),
    enabled: tab === 'memory',
    staleTime: 15_000,
  })

  const [memDraft, setMemDraft] = useState('')
  useEffect(() => {
    if (memoryRow && typeof memoryRow.content === 'string') setMemDraft(memoryRow.content)
  }, [memoryRow])

  const saveMem = useMutation({
    mutationFn: () => putMemory(MODE, memDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['memory', MODE] }),
  })

  const extractMem = useMutation({
    mutationFn: () => extractMemory(MODE),
    onSuccess: (r) => {
      if (r?.content != null) setMemDraft(r.content)
      queryClient.invalidateQueries({ queryKey: ['memory', MODE] })
    },
  })

  const { data: dawPack } = useQuery({
    queryKey: ['daws', MODE],
    queryFn: () => listDaws(MODE),
    enabled: tab === 'daw',
    staleTime: 15_000,
  })
  const daws = dawPack?.items ?? []

  const { data: entriesRaw } = useQuery({
    queryKey: ['memory', 'entries'],
    queryFn: listMemoryEntries,
    enabled: tab === 'memory',
    staleTime: 15_000,
  })
  const memoryEntries = Array.isArray(entriesRaw) ? entriesRaw : []

  const { data: globalInstrRow } = useQuery({
    queryKey: ['custom-instructions', 'global'],
    queryFn: () => getCustomInstructions('global'),
    enabled: tab === 'instructions',
    staleTime: 15_000,
  })
  const { data: booopsInstrRow } = useQuery({
    queryKey: ['custom-instructions', 'booops'],
    queryFn: () => getCustomInstructions('booops'),
    enabled: tab === 'instructions',
    staleTime: 15_000,
  })

  const [gInstrDraft, setGInstrDraft] = useState('')
  const [bInstrDraft, setBInstrDraft] = useState('')
  useEffect(() => {
    if (globalInstrRow && typeof globalInstrRow.content === 'string') setGInstrDraft(globalInstrRow.content)
  }, [globalInstrRow])
  useEffect(() => {
    if (booopsInstrRow && typeof booopsInstrRow.content === 'string') setBInstrDraft(booopsInstrRow.content)
  }, [booopsInstrRow])

  const [entryAdding, setEntryAdding] = useState(false)
  const [entryNewContent, setEntryNewContent] = useState('')
  const [entryEditId, setEntryEditId] = useState(null)
  const [entryEditContent, setEntryEditContent] = useState('')

  const saveGlobalInstr = useMutation({
    mutationFn: () => putCustomInstructions('global', gInstrDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['custom-instructions', 'global'] }),
  })
  const saveBooopsInstr = useMutation({
    mutationFn: () => putCustomInstructions('booops', bInstrDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['custom-instructions', 'booops'] }),
  })

  const addEntry = useMutation({
    mutationFn: () => createMemoryEntry(entryNewContent.trim()),
    onSuccess: () => {
      setEntryAdding(false)
      setEntryNewContent('')
      queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] })
    },
  })
  const saveEntry = useMutation({
    mutationFn: () => updateMemoryEntry(entryEditId, entryEditContent.trim()),
    onSuccess: () => {
      setEntryEditId(null)
      queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] })
    },
  })
  const delEntry = useMutation({
    mutationFn: (id) => deleteMemoryEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] }),
  })

  const invalidatePersonas = useCallback(async () => {
    await queryClient.refetchQueries({ queryKey: ['personas'] })
    const pack = queryClient.getQueryData(['personas'])
    const items = pack?.items
    if (Array.isArray(items)) setPersonas(items)
  }, [queryClient, setPersonas])

  const personaIconInputRef = useRef(null)
  const uploadPersonaIconMut = useMutation({
    mutationFn: ({ id, file }) => uploadPersonaIcon(id, file),
    onSuccess: () => invalidatePersonas(),
  })
  const clearPersonaIconMut = useMutation({
    mutationFn: (id) => updatePersona(id, { icon_url: null }),
    onSuccess: () => invalidatePersonas(),
  })

  const [pForm, setPForm] = useState(null)
  const [pEmoji, setPEmoji] = useState('🤖')
  const [pName, setPName] = useState('')
  const [pPrompt, setPPrompt] = useState('')

  function openNewPersona() {
    setPForm('new')
    setPEmoji('🤖')
    setPName('')
    setPPrompt('')
  }

  function openEditPersona(p) {
    setPForm(p.id)
    setPEmoji(p.avatar_emoji || '🤖')
    setPName(p.name || '')
    setPPrompt(p.system_prompt || '')
  }

  const savePersona = useMutation({
    mutationFn: async () => {
      if (pForm === 'new') {
        return createPersona({
          name: pName.trim() || 'Unnamed',
          system_prompt: pPrompt,
          avatar_emoji: pEmoji.trim() || '🤖',
        })
      }
      return updatePersona(pForm, {
        name: pName.trim() || 'Unnamed',
        system_prompt: pPrompt,
        avatar_emoji: pEmoji.trim() || '🤖',
      })
    },
    onSuccess: () => {
      setPForm(null)
      invalidatePersonas()
    },
  })

  const setDefaultPersona = useMutation({
    mutationFn: (id) => updatePersona(id, { is_default_booops: true }),
    onSuccess: async () => {
      await invalidatePersonas()
      const def = useAppStore.getState().personas.find((p) => p.is_default_booops)
      if (def) setActivePersonaId(def.id)
    },
  })

  const delPersona = useMutation({
    mutationFn: (id) => deletePersona(id),
    onSuccess: () => invalidatePersonas(),
  })

  const [wForm, setWForm] = useState(null)
  const [wName, setWName] = useState('')
  const [wPrompt, setWPrompt] = useState('')
  const [wPersonaId, setWPersonaId] = useState(null)
  const [wColor, setWColor] = useState('#7c3aed')

  function openNewDaw() {
    setWForm('new')
    setWName('')
    setWPrompt('')
    setWPersonaId(null)
    setWColor('#7c3aed')
  }

  function openEditDaw(w) {
    setWForm(w.id)
    setWName(w.name || '')
    setWPrompt(w.system_prompt || '')
    setWPersonaId(w.persona_id ?? null)
    setWColor(w.color || '#7c3aed')
  }

  const saveDaw = useMutation({
    mutationFn: async () => {
      const body = {
        mode: MODE,
        name: wName.trim() || 'Untitled',
        system_prompt: wPrompt,
        persona_id: wPersonaId || null,
        color: wColor || '#7c3aed',
      }
      if (wForm === 'new') return createDaw(body)
      return updateDaw(wForm, {
        name: body.name,
        system_prompt: body.system_prompt,
        persona_id: body.persona_id,
        color: body.color,
      })
    },
    onSuccess: () => {
      setWForm(null)
      queryClient.invalidateQueries({ queryKey: ['daws', MODE] })
    },
  })

  const delDaw = useMutation({
    mutationFn: (id) => deleteDaw(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['daws', MODE] }),
  })

  const { data: globalSettings } = useQuery({
    queryKey: ['settings', 'global'],
    queryFn: getGlobalSettings,
    enabled: tab === 'ollama',
    staleTime: 15_000,
  })
  const [gCtxDraft, setGCtxDraft] = useState(16384)
  const [gTempDraft, setGTempDraft] = useState(0.7)
  const [gTopPDraft, setGTopPDraft] = useState(1.0)
  const [gTopKDraft, setGTopKDraft] = useState(20)
  const [gMaxTokensDraft, setGMaxTokensDraft] = useState(2048)
  useEffect(() => {
    const v = globalSettings?.context_window_global
    if (typeof v === 'number' && !Number.isNaN(v)) setGCtxDraft(v)
    if (typeof globalSettings?.temperature_global === 'number') setGTempDraft(globalSettings.temperature_global)
    if (typeof globalSettings?.top_p_global === 'number') setGTopPDraft(globalSettings.top_p_global)
    if (typeof globalSettings?.top_k_global === 'number') setGTopKDraft(globalSettings.top_k_global)
    if (typeof globalSettings?.max_tokens_global === 'number') setGMaxTokensDraft(globalSettings.max_tokens_global)
  }, [globalSettings])

  const saveGlobalCtx = useMutation({
    mutationFn: () =>
      patchGlobalSettings({
        context_window_global: gCtxDraft,
        temperature_global: gTempDraft,
        top_p_global: gTopPDraft,
        top_k_global: gTopKDraft,
        max_tokens_global: gMaxTokensDraft,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings', 'global'] }),
  })

  const { data: ollamaConfig } = useQuery({
    queryKey: ['settings', 'ollama'],
    queryFn: getOllamaConfig,
    enabled: tab === 'ollama',
    staleTime: 15_000,
  })
  const [ollFlash, setOllFlash] = useState(true)
  const [ollMaxLoaded, setOllMaxLoaded] = useState(1)
  const [ollKeepAlive, setOllKeepAlive] = useState('30m')
  useEffect(() => {
    if (!ollamaConfig) return
    if (typeof ollamaConfig.flash_attention === 'boolean') setOllFlash(ollamaConfig.flash_attention)
    const ml = ollamaConfig.max_loaded_models
    if (typeof ml === 'number' && !Number.isNaN(ml)) setOllMaxLoaded(ml)
    if (typeof ollamaConfig.keep_alive === 'string') setOllKeepAlive(ollamaConfig.keep_alive)
  }, [ollamaConfig])

  const saveOllamaConfigMut = useMutation({
    mutationFn: () =>
      patchOllamaConfig({
        flash_attention: ollFlash,
        max_loaded_models: ollMaxLoaded,
        keep_alive: ollKeepAlive.trim() || '30m',
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings', 'ollama'] }),
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <div className="border-b border-border px-4 py-4">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">AI</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Personas, memory, DAWs, and shared model settings (same data in BooOps, 808notes, and boolab AI).
        </p>
        <div className="mt-4 flex gap-1 border-b border-border">
          {[
            { id: 'personas', label: 'Personas' },
            { id: 'memory', label: 'Memory' },
            { id: 'daw', label: 'DAW' },
            { id: 'ollama', label: 'Ollama' },
            { id: 'instructions', label: 'Instructions' },
          ].map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={cn(
                '-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                tab === t.id
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="mx-auto w-full max-w-3xl flex-1 px-4 py-6">
        {tab === 'personas' && (
          <div className="flex flex-col gap-4">
            <div className="flex justify-end">
              <Button type="button" size="sm" onClick={openNewPersona}>
                New persona
              </Button>
            </div>

            {pForm && (
              <div className="rounded-lg border border-border bg-card p-4">
                <p className="mb-3 text-sm font-medium text-foreground">
                  {pForm === 'new' ? 'New persona' : 'Edit persona'}
                </p>
                <div className="flex flex-col gap-3">
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Emoji</span>
                    <div className="flex flex-wrap items-center gap-3">
                      <input
                        value={pEmoji}
                        onChange={(e) => setPEmoji(e.target.value)}
                        className="h-9 w-24 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                        maxLength={8}
                      />
                      {pForm !== 'new' ? (
                        (() => {
                          const ep = personas.find((x) => x.id === pForm)
                          return ep?.icon_url ? (
                            <img src={ep.icon_url} alt="" className="size-10 rounded-full object-cover" />
                          ) : null
                        })()
                      ) : null}
                    </div>
                  </label>
                  <div className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Avatar image (overrides emoji)</span>
                    {pForm === 'new' ? (
                      <p className="text-xs text-muted-foreground">Save first, then upload an image.</p>
                    ) : (
                      <>
                        <input
                          ref={personaIconInputRef}
                          type="file"
                          accept="image/*"
                          className="hidden"
                          onChange={(e) => {
                            const f = e.target.files?.[0]
                            e.target.value = ''
                            if (f) uploadPersonaIconMut.mutate({ id: pForm, file: f })
                          }}
                        />
                        <div className="flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            onClick={() => personaIconInputRef.current?.click()}
                            disabled={uploadPersonaIconMut.isPending}
                          >
                            {uploadPersonaIconMut.isPending ? 'Uploading…' : 'Choose image'}
                          </Button>
                          {personas.find((x) => x.id === pForm)?.icon_url ? (
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => clearPersonaIconMut.mutate(pForm)}
                              disabled={clearPersonaIconMut.isPending}
                            >
                              Remove image
                            </Button>
                          ) : null}
                        </div>
                      </>
                    )}
                  </div>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Name</span>
                    <input
                      value={pName}
                      onChange={(e) => setPName(e.target.value)}
                      className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">System prompt</span>
                    <textarea
                      value={pPrompt}
                      onChange={(e) => setPPrompt(e.target.value)}
                      rows={6}
                      className="resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                    />
                  </label>
                  <div className="flex gap-2">
                    <Button type="button" size="sm" onClick={() => savePersona.mutate()} disabled={savePersona.isPending}>
                      Save
                    </Button>
                    <Button type="button" size="sm" variant="outline" onClick={() => setPForm(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              </div>
            )}

            <ul className="flex flex-col gap-3">
              {personas.map((p) => (
                <li
                  key={p.id}
                  className="rounded-lg border border-border bg-card p-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        {p.icon_url ? (
                          <img src={p.icon_url} alt="" className="size-10 shrink-0 rounded-full object-cover" />
                        ) : (
                          <span className="text-xl" aria-hidden>
                            {p.avatar_emoji || '🤖'}
                          </span>
                        )}
                        <span className="font-medium text-foreground">{p.name}</span>
                        {p.is_default_booops && (
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                            Default (BooOps)
                          </span>
                        )}
                        {p.is_default_808notes && (
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                            Default (808notes)
                          </span>
                        )}
                      </div>
                      <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{p.system_prompt || '—'}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button type="button" size="sm" variant="secondary" onClick={() => openEditPersona(p)}>
                        Edit
                      </Button>
                      {!p.is_default_booops && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => setDefaultPersona.mutate(p.id)}
                          disabled={setDefaultPersona.isPending}
                        >
                          Set BooOps default
                        </Button>
                      )}
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={p.is_default_booops || p.is_default_808notes}
                        onClick={() => delPersona.mutate(p.id)}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {tab === 'memory' && (
          <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-3">
              {memoryRow?.updated_at && (
                <p className="text-xs text-muted-foreground">Last updated: {memoryRow.updated_at}</p>
              )}
              {memLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
              <textarea
                value={memDraft}
                onChange={(e) => setMemDraft(e.target.value)}
                rows={18}
                className="min-h-[12rem] w-full resize-y rounded-md border border-border bg-card px-3 py-2 font-mono text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                placeholder="Markdown: headings and bullet lists…"
              />
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => saveMem.mutate()} disabled={saveMem.isPending}>
                  Save
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => extractMem.mutate()}
                  disabled={extractMem.isPending}
                >
                  {extractMem.isPending ? 'Extracting…' : 'Extract from recent chat'}
                </Button>
              </div>
            </div>

            <div className="flex flex-col gap-4 border-t border-border pt-6">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-sm font-medium text-foreground">Entries</h2>
                <Button type="button" size="sm" onClick={() => setEntryAdding((a) => !a)}>
                  Add entry
                </Button>
              </div>
              {entryAdding && (
                <div className="rounded-lg border border-border bg-card p-4">
                  <textarea
                    value={entryNewContent}
                    onChange={(e) => setEntryNewContent(e.target.value)}
                    rows={3}
                    className="mb-3 w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                    placeholder="Memory entry…"
                  />
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => addEntry.mutate()}
                      disabled={addEntry.isPending || !entryNewContent.trim()}
                    >
                      Save
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setEntryAdding(false)
                        setEntryNewContent('')
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
              {memoryEntries.length === 0 && !entryAdding ? (
                <p className="text-sm text-muted-foreground">No memory entries</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {memoryEntries.map((e) => (
                    <li key={e.id} className="rounded-lg border border-border bg-card p-4">
                      {entryEditId === e.id ? (
                        <div className="flex flex-col gap-2">
                          <textarea
                            value={entryEditContent}
                            onChange={(ev) => setEntryEditContent(ev.target.value)}
                            rows={3}
                            className="w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                          />
                          <div className="flex gap-2">
                            <Button
                              type="button"
                              size="sm"
                              onClick={() => saveEntry.mutate()}
                              disabled={saveEntry.isPending || !entryEditContent.trim()}
                            >
                              Save
                            </Button>
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              onClick={() => setEntryEditId(null)}
                            >
                              Cancel
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <p className="line-clamp-3 whitespace-pre-wrap text-sm text-foreground">{e.content}</p>
                            <span
                              className={cn(
                                'mt-2 inline-block rounded-full px-2 py-0.5 text-xs font-medium',
                                e.source === 'auto'
                                  ? 'bg-secondary text-secondary-foreground'
                                  : 'bg-muted text-muted-foreground',
                              )}
                            >
                              {e.source || 'manual'}
                            </span>
                          </div>
                          <div className="flex shrink-0 gap-2">
                            <Button
                              type="button"
                              size="sm"
                              variant="secondary"
                              onClick={() => {
                                setEntryEditId(e.id)
                                setEntryEditContent(e.content || '')
                              }}
                            >
                              Edit
                            </Button>
                            <Button type="button" size="sm" variant="destructive" onClick={() => delEntry.mutate(e.id)}>
                              Delete
                            </Button>
                          </div>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}

        {tab === 'ollama' && (
          <div className="flex flex-col gap-6">
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-medium text-foreground">Global context window</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Default context size for chats that use the DAW model picker (no pinned model on the DAW). DAWs with a
                pinned model use that DAW’s context window instead.
              </p>
              <div className="flex flex-col gap-4 text-sm">
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Context window (tokens)</span>
                    <span className="tabular-nums text-foreground">{gCtxDraft}</span>
                  </div>
                  <input
                    type="range"
                    min={1024}
                    max={32768}
                    step={1024}
                    value={gCtxDraft}
                    onChange={(e) => setGCtxDraft(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                </div>
                <div className="flex flex-col gap-2 border-t border-border pt-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Temperature</span>
                    <span className="tabular-nums text-foreground">{gTempDraft}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.05}
                    value={gTempDraft}
                    onChange={(e) => setGTempDraft(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <p className="text-xs text-muted-foreground">
                    Default temperature for chats using DAW model picker. DAW overrides this.
                  </p>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Top-p</span>
                    <span className="tabular-nums text-foreground">{gTopPDraft}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.05}
                    value={gTopPDraft}
                    onChange={(e) => setGTopPDraft(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <p className="text-xs text-muted-foreground">Nucleus sampling. DAW overrides this.</p>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Top-k</span>
                    <span className="tabular-nums text-foreground">{gTopKDraft}</span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={100}
                    step={1}
                    value={gTopKDraft}
                    onChange={(e) => setGTopKDraft(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <p className="text-xs text-muted-foreground">Token sampling pool. Ollama only. DAW overrides this.</p>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Max tokens</span>
                    <span className="tabular-nums text-foreground">{gMaxTokensDraft}</span>
                  </div>
                  <input
                    type="range"
                    min={256}
                    max={8192}
                    step={256}
                    value={gMaxTokensDraft}
                    onChange={(e) => setGMaxTokensDraft(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <p className="text-xs text-muted-foreground">Default max response tokens. DAW overrides this.</p>
                </div>
                <Button type="button" size="sm" onClick={() => saveGlobalCtx.mutate()} disabled={saveGlobalCtx.isPending}>
                  Save
                </Button>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-1 text-sm font-medium text-foreground">DAW</h2>
              <p className="text-xs text-muted-foreground">
                BooOps and 808notes each have DAW model settings here. Pull, delete, and unload apply to the shared
                Ollama server.
              </p>
              <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Ollama DAW">
                <Button
                  type="button"
                  size="sm"
                  variant={ollamaDawMode === 'booops' ? 'default' : 'outline'}
                  onClick={() => setOllamaDawMode('booops')}
                >
                  BooOps
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant={ollamaDawMode === '808notes' ? 'default' : 'outline'}
                  onClick={() => setOllamaDawMode('808notes')}
                >
                  808notes
                </Button>
              </div>
            </div>

            <OllamaDawModelsSection
              queryClient={queryClient}
              selectClass={OLLAMA_SELECT_CLASS}
              mode={ollamaDawMode}
            />

            {ollamaDawMode === '808notes' ? <Claude808notesModelPrefs /> : null}

            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-medium text-foreground">Ollama config</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Changes apply to next Ollama restart on sam-desktop.
              </p>
              <div className="flex flex-col gap-4 text-sm">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={ollFlash}
                    onChange={(e) => setOllFlash(e.target.checked)}
                    className="size-4 rounded border-border accent-primary"
                  />
                  <span className="text-foreground">Flash attention</span>
                </label>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Max loaded models</span>
                    <span className="tabular-nums text-foreground">{ollMaxLoaded}</span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={8}
                    step={1}
                    value={ollMaxLoaded}
                    onChange={(e) => setOllMaxLoaded(Number(e.target.value))}
                    className="h-2 w-full max-w-md cursor-pointer accent-primary"
                  />
                </div>
                <label className="flex max-w-md flex-col gap-1">
                  <span className="text-muted-foreground">Keep alive</span>
                  <input
                    value={ollKeepAlive}
                    onChange={(e) => setOllKeepAlive(e.target.value)}
                    placeholder="30m, 1h, 0, …"
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                  />
                </label>
                <Button
                  type="button"
                  size="sm"
                  className="w-fit"
                  onClick={() => saveOllamaConfigMut.mutate()}
                  disabled={saveOllamaConfigMut.isPending}
                >
                  Save
                </Button>
              </div>
            </div>
          </div>
        )}

        {tab === 'instructions' && (
          <div className="flex flex-col gap-6">
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-medium text-foreground">Global instructions</h2>
              <textarea
                value={gInstrDraft}
                onChange={(e) => setGInstrDraft(e.target.value)}
                rows={6}
                className="mb-3 w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
              />
              <Button type="button" size="sm" onClick={() => saveGlobalInstr.mutate()} disabled={saveGlobalInstr.isPending}>
                Save
              </Button>
            </div>
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-medium text-foreground">BooOps instructions</h2>
              <textarea
                value={bInstrDraft}
                onChange={(e) => setBInstrDraft(e.target.value)}
                rows={6}
                className="mb-3 w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
              />
              <Button type="button" size="sm" onClick={() => saveBooopsInstr.mutate()} disabled={saveBooopsInstr.isPending}>
                Save
              </Button>
            </div>
          </div>
        )}

        {tab === 'daw' && (
          <div className="flex flex-col gap-4">
            <div className="flex justify-end">
              <Button type="button" size="sm" onClick={openNewDaw}>
                New DAW
              </Button>
            </div>

            {wForm && (
              <div className="rounded-lg border border-border bg-card p-4">
                <p className="mb-3 text-sm font-medium text-foreground">
                  {wForm === 'new' ? 'New DAW' : 'Edit DAW'}
                </p>
                <div className="flex flex-col gap-3">
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Name</span>
                    <input
                      value={wName}
                      onChange={(e) => setWName(e.target.value)}
                      className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Persona</span>
                    <PersonaPickerButton
                      label="Default persona"
                      value={wPersonaId}
                      personas={personas}
                      onChange={setWPersonaId}
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">System prompt</span>
                    <textarea
                      value={wPrompt}
                      onChange={(e) => setWPrompt(e.target.value)}
                      rows={5}
                      className="resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">Color</span>
                    <input
                      type="color"
                      value={wColor}
                      onChange={(e) => setWColor(e.target.value)}
                      className="h-9 w-24 cursor-pointer rounded-md border border-border bg-background"
                    />
                  </label>
                  <div className="flex gap-2">
                    <Button type="button" size="sm" onClick={() => saveDaw.mutate()} disabled={saveDaw.isPending}>
                      Save
                    </Button>
                    <Button type="button" size="sm" variant="outline" onClick={() => setWForm(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              </div>
            )}

            <ul className="flex flex-col gap-3">
              {daws.map((w) => (
                <li key={w.id} className="rounded-lg border border-border bg-card p-4">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className="size-3 shrink-0 rounded-full"
                          style={{ background: w.color || '#7c3aed' }}
                          aria-hidden
                        />
                        <p className="font-medium text-foreground">{w.name}</p>
                      </div>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Persona: {w.persona_name || 'Default persona'}
                      </p>
                      <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{w.system_prompt || '—'}</p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <Button type="button" size="sm" variant="secondary" onClick={() => openEditDaw(w)}>
                        Edit
                      </Button>
                      <Button type="button" size="sm" variant="destructive" onClick={() => delDaw.mutate(w.id)}>
                        Delete
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
