import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { Check, ChevronDown, Search } from 'lucide-react'

import { listDaws } from '@/api/daws.js'
import { listPersonas } from '@/api/personas.js'
import { DEFAULT_OLLAMA_MODEL, fetchOllamaModels, getOllamaSettings } from '@/api/ollama.js'
import { getChat, patchChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn, sortSelectedFirst } from '@/lib/utils'
import { is808notesRouteContext } from '@/routes/paths.js'

import { PersonaGlyph } from './PersonaGlyph.jsx'

const CLAUDE_PICKER_MODELS = [
  { name: 'claude-sonnet', size: null },
  { name: 'claude-haiku', size: null },
  { name: 'claude-opus', size: null },
]

function read808notesClaudeEnabled() {
  try {
    return localStorage.getItem('808notes_claude_enabled') === 'true'
  } catch {
    return false
  }
}

function formatModelSize(bytes) {
  if (bytes == null || Number.isNaN(bytes)) return '—'
  const n = Number(bytes)
  if (n <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  const dec = v >= 10 || i === 0 ? 0 : 1
  return `${v.toFixed(dec)} ${units[i]}`
}

function useFixedRect(anchorRef, open) {
  const [rect, setRect] = useState(null)
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return
    setRect(anchorRef.current.getBoundingClientRect())
  }, [open, anchorRef])
  return rect
}

function FixedDropdownPanel({ rect, children, className, minWidthPx }) {
  if (!rect) return null
  const w = minWidthPx != null ? Math.max(rect.width, minWidthPx) : rect.width
  return (
    <div
      className={cn('flex min-w-0 flex-col gap-2 overflow-x-hidden p-2', className)}
      style={{
        zIndex: 9999,
        position: 'fixed',
        top: `${rect.bottom}px`,
        left: `${rect.left}px`,
        width: `${w}px`,
        maxWidth: 'calc(100vw - 1rem)',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
      role="dialog"
    >
      {children}
    </div>
  )
}

export function ModelSelectorBar({
  className,
  hidePersona = false,
  /** When true, omit DAW picker UI (808notes DAW workspace). Reserved for bar extensions. */
  hideDaw: _hideDaw = false,
}) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const storeMode = useAppStore((s) => s.mode)
  const is808notes = is808notesRouteContext(location.pathname, storeMode)

  const [modelOpen, setModelOpen] = useState(false)
  const [personaOpen, setPersonaOpen] = useState(false)
  const [q, setQ] = useState('')

  const modelWrapRef = useRef(null)
  const modelBtnRef = useRef(null)
  const personaBtnRef = useRef(null)
  const personaWrapRef = useRef(null)

  const modelRect = useFixedRect(modelBtnRef, modelOpen)
  const personaRect = useFixedRect(personaBtnRef, personaOpen)

  const selectedModel = useAppStore((s) => s.selectedModel)
  const setSelectedModel = useAppStore((s) => s.setSelectedModel)
  const setDefaultModel = useAppStore((s) => s.setDefaultModel)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const userTouchedLandingModelRef = useRef(false)
  const prevActiveChatIdRef = useRef(activeChatId)
  const storePersonaId = useAppStore((s) => s.activePersonaId)
  const storeDawId = useAppStore((s) => s.activeDawId)
  const setActivePersonaId = useAppStore((s) => s.setActivePersonaId)

  const { data: ollamaData, isLoading: modelsLoading } = useQuery({
    queryKey: ['ollama', 'models'],
    queryFn: fetchOllamaModels,
    staleTime: 60_000,
  })

  const ollamaSettingsMode = is808notes ? '808notes' : 'booops'
  const { data: ollamaSettings, isLoading: settingsLoading } = useQuery({
    queryKey: ['ollama', 'settings', ollamaSettingsMode],
    queryFn: () => getOllamaSettings(ollamaSettingsMode),
    staleTime: 60_000,
  })

  const hiddenNames = useMemo(
    () => new Set(Array.isArray(ollamaSettings?.hidden_models) ? ollamaSettings.hidden_models : []),
    [ollamaSettings],
  )

  const { data: personaPack } = useQuery({
    queryKey: ['personas'],
    queryFn: () => listPersonas(),
    staleTime: 30_000,
  })
  const personas = personaPack?.items ?? []
  const defaultPersona = useMemo(() => {
    if (is808notes) return personas.find((p) => p.is_default_808notes) ?? null
    return personas.find((p) => p.is_default_booops) ?? null
  }, [personas, is808notes])

  const { data: chat } = useQuery({
    queryKey: ['chat', activeChatId],
    queryFn: () => getChat(activeChatId),
    enabled: Boolean(activeChatId),
  })

  const { data: dawPack } = useQuery({
    queryKey: ['daws', is808notes ? '808notes' : 'booops'],
    queryFn: () => listDaws(is808notes ? '808notes' : 'booops'),
    staleTime: 30_000,
  })
  const daws = dawPack?.items ?? []

  const [claudePickerRev, setClaudePickerRev] = useState(0)
  useEffect(() => {
    const fn = () => setClaudePickerRev((x) => x + 1)
    window.addEventListener('808notes-models', fn)
    return () => window.removeEventListener('808notes-models', fn)
  }, [])

  const models = useMemo(() => {
    const raw = Array.isArray(ollamaData?.models) ? ollamaData.models : []
    let list = raw
      .map((m) => ({
        name: typeof m?.name === 'string' ? m.name : '',
        size: m?.size,
      }))
      .filter((m) => m.name && !hiddenNames.has(m.name))
    if (is808notes && read808notesClaudeEnabled()) {
      const have = new Set(list.map((m) => m.name))
      for (const c of CLAUDE_PICKER_MODELS) {
        if (!have.has(c.name)) list = [...list, c]
      }
    }
    return list
  }, [ollamaData, hiddenNames, is808notes, claudePickerRev])

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return models
    return models.filter((m) => m.name.toLowerCase().includes(s))
  }, [models, q])

  const sortedFiltered = useMemo(
    () => sortSelectedFirst(filtered, selectedModel, 'name'),
    [filtered, selectedModel],
  )

  const chatPersonaId = chat?.persona_id ?? null
  const chatDawId = chat?.daw_id ?? null
  const effectivePersonaId = activeChatId ? chatPersonaId : storePersonaId
  const effectiveDawId = activeChatId ? chatDawId : storeDawId

  const displayPersona = useMemo(() => {
    if (effectivePersonaId) return personas.find((p) => p.id === effectivePersonaId) ?? defaultPersona
    return defaultPersona
  }, [effectivePersonaId, personas, defaultPersona])

  const displayDaw = useMemo(() => {
    if (!effectiveDawId) return null
    return daws.find((w) => w.id === effectiveDawId) ?? null
  }, [effectiveDawId, daws])

  const dawPinnedModel = useMemo(
    () => (displayDaw?.model && String(displayDaw.model).trim()) || '',
    [displayDaw?.model],
  )
  const modelLocked = Boolean(dawPinnedModel && (activeChatId ? chatDawId : storeDawId))

  const sortedPersonas = useMemo(
    () => sortSelectedFirst(personas, effectivePersonaId || defaultPersona?.id, 'id'),
    [personas, effectivePersonaId, defaultPersona],
  )

  useEffect(() => {
    const prev = prevActiveChatIdRef.current
    prevActiveChatIdRef.current = activeChatId
    if (prev && !activeChatId) userTouchedLandingModelRef.current = false
  }, [activeChatId])

  useEffect(() => {
    const v = String(ollamaSettings?.default_model ?? '').trim()
    setDefaultModel(v || DEFAULT_OLLAMA_MODEL)
  }, [ollamaSettings?.default_model, setDefaultModel])

  useEffect(() => {
    if (!modelLocked || !dawPinnedModel) return
    if (selectedModel !== dawPinnedModel) setSelectedModel(dawPinnedModel)
  }, [modelLocked, dawPinnedModel, selectedModel, setSelectedModel])

  useEffect(() => {
    if (activeChatId != null) return
    if (modelLocked) return
    if (modelsLoading || settingsLoading) return
    if (!models.length) return
    if (userTouchedLandingModelRef.current) return
    const def = String(ollamaSettings?.default_model ?? '').trim() || DEFAULT_OLLAMA_MODEL
    const pick = models.some((m) => m.name === def)
      ? def
      : (models.find((m) => m.name === DEFAULT_OLLAMA_MODEL)?.name ?? models[0].name)
    if (useAppStore.getState().selectedModel === pick) return
    setSelectedModel(pick)
  }, [
    activeChatId,
    modelsLoading,
    settingsLoading,
    models,
    ollamaSettings?.default_model,
    setSelectedModel,
    modelLocked,
  ])

  useEffect(() => {
    if (!modelOpen) return
    function onMouseDown(e) {
      if (modelWrapRef.current && !modelWrapRef.current.contains(e.target)) {
        setModelOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [modelOpen])

  useEffect(() => {
    if (!modelOpen) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setModelOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [modelOpen])

  useEffect(() => {
    if (!personaOpen) return
    function onMouseDown(e) {
      if (personaWrapRef.current && !personaWrapRef.current.contains(e.target)) {
        setPersonaOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [personaOpen])

  useEffect(() => {
    if (!personaOpen) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setPersonaOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [personaOpen])

  async function selectModel(name) {
    if (modelLocked) return
    if (!activeChatId) userTouchedLandingModelRef.current = true
    setSelectedModel(name)
    setModelOpen(false)
    setQ('')
    if (activeChatId) {
      try {
        await patchChat(activeChatId, { model: name })
        await queryClient.invalidateQueries({ queryKey: ['chat', activeChatId] })
      } catch {
        /* ignore */
      }
    }
  }

  async function selectPersona(id) {
    setPersonaOpen(false)
    if (!activeChatId) {
      setActivePersonaId(id)
      return
    }
    try {
      await patchChat(activeChatId, { persona_id: id })
      await queryClient.invalidateQueries({ queryKey: ['chat', activeChatId] })
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch {
      /* ignore */
    }
  }

  async function clearPersonaToDefault() {
    setPersonaOpen(false)
    if (!activeChatId) {
      if (defaultPersona) setActivePersonaId(defaultPersona.id)
      return
    }
    try {
      await patchChat(activeChatId, { persona_id: null })
      await queryClient.invalidateQueries({ queryKey: ['chat', activeChatId] })
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch {
      /* ignore */
    }
  }

  const displayName = (modelLocked ? dawPinnedModel : selectedModel) || 'Select model'

  return (
    <div className={cn('flex min-w-0 flex-wrap items-center justify-center gap-2', className)}>
      <div ref={modelWrapRef} className="relative">
        <span ref={modelBtnRef} className="inline-flex">
          <Button
            type="button"
            variant="ghost"
            disabled={modelLocked}
            title={modelLocked ? 'Model pinned by DAW (change on DAW detail page)' : undefined}
            className="h-9 max-w-full gap-2 px-3 font-normal text-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-60"
            aria-expanded={modelOpen}
            aria-haspopup="dialog"
            onClick={() => {
              if (modelLocked) return
              setModelOpen((o) => !o)
            }}
          >
            <span className="truncate text-sm font-medium">{displayName}</span>
            <ChevronDown className="size-4 shrink-0 opacity-70" aria-hidden />
          </Button>
        </span>
        {modelOpen && (
          <FixedDropdownPanel rect={modelRect} minWidthPx={288}>
            <div className="relative min-w-0">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <input
                type="search"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search…"
                className="h-9 w-full min-w-0 rounded-md border border-border bg-card py-2 pl-8 pr-2 text-sm text-foreground outline-none ring-ring placeholder:text-muted-foreground focus-visible:ring-2"
              />
            </div>
            <div className="min-h-0 min-w-0 max-h-[min(50vh,20rem)] overflow-y-auto overflow-x-hidden">
              {modelsLoading && (
                <p className="px-2 py-3 text-center text-sm text-muted-foreground">Loading models…</p>
              )}
              {!modelsLoading && filtered.length === 0 && (
                <p className="px-2 py-3 text-center text-sm text-muted-foreground">No models match</p>
              )}
              <ul className="flex min-w-0 flex-col gap-0.5">
                {sortedFiltered.map((m) => {
                  const sel = m.name === selectedModel
                  return (
                    <li key={m.name} className="min-w-0">
                      <button
                        type="button"
                        className={cn(
                          'flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground',
                          sel && 'bg-muted',
                        )}
                        onClick={() => selectModel(m.name)}
                      >
                        <span className="size-8 shrink-0 rounded-full border border-border bg-muted" aria-hidden />
                        <span className="min-w-0 flex-1 truncate font-medium text-foreground">{m.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground">{formatModelSize(m.size)}</span>
                        {sel && (
                          <span
                            className="size-2 shrink-0 rounded-full"
                            style={{ background: 'var(--success, var(--accent-2))' }}
                            title="Active"
                          />
                        )}
                        {sel && <Check className="size-4 shrink-0 text-primary" aria-label="Selected" />}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          </FixedDropdownPanel>
        )}
      </div>

      {!hidePersona && (
        <div ref={personaWrapRef} className="relative">
          <span ref={personaBtnRef} className="inline-flex">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-9 max-w-[10rem] gap-1.5 border-border bg-card px-2.5 font-normal"
              aria-expanded={personaOpen}
              aria-haspopup="listbox"
              onClick={() => setPersonaOpen((o) => !o)}
            >
              <PersonaGlyph kind="trigger" iconUrl={displayPersona?.icon_url} emoji={displayPersona?.avatar_emoji} />
              <span className="truncate text-xs font-medium">{displayPersona?.name || 'Persona'}</span>
              <ChevronDown className="size-3 shrink-0 opacity-70" aria-hidden />
            </Button>
          </span>
          {personaOpen && (
            <FixedDropdownPanel rect={personaRect} className="min-w-[12rem]">
              <ul className="max-h-[min(50vh,18rem)] overflow-y-auto" role="listbox">
                <li>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground"
                    onClick={() => clearPersonaToDefault()}
                  >
                    <PersonaGlyph
                      kind="list"
                      iconUrl={defaultPersona?.icon_url}
                      emoji={defaultPersona?.avatar_emoji}
                    />
                    <span className="truncate">Default ({defaultPersona?.name || 'BooOps'})</span>
                    {!effectivePersonaId && <Check className="ml-auto size-4 shrink-0 text-primary" />}
                  </button>
                </li>
                {sortedPersonas.map((p) => {
                  const sel = effectivePersonaId === p.id
                  return (
                    <li key={p.id}>
                      <button
                        type="button"
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md px-2 py-2 text-left text-sm hover:bg-accent hover:text-accent-foreground',
                          sel && 'bg-muted',
                        )}
                        onClick={() => selectPersona(p.id)}
                      >
                        <PersonaGlyph kind="list" iconUrl={p.icon_url} emoji={p.avatar_emoji} />
                        <span className="min-w-0 flex-1 truncate">{p.name}</span>
                        {sel && <Check className="size-4 shrink-0 text-primary" />}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </FixedDropdownPanel>
          )}
        </div>
      )}
    </div>
  )
}
