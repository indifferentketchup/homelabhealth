import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, ChevronDown, Search } from 'lucide-react'

import { listWorkspaces } from '@/api/workspaces.js'
import { listPersonas } from '@/api/personas.js'
import { fetchModels, getModelSettings } from '@/api/inference.js'
import { getChat, patchChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn, sortSelectedFirst } from '@/lib/utils'

import { PersonaGlyph } from './PersonaGlyph.jsx'

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
      className={cn(
        'fixed z-[9999] flex min-w-0 flex-col gap-2 overflow-x-hidden rounded-lg border border-border p-2 shadow-xl',
        className,
      )}
      style={{
        top: `${rect.bottom}px`,
        left: `${rect.left}px`,
        width: `${w}px`,
        maxWidth: 'calc(100vw - 1rem)',
        background: 'var(--bg-panel)',
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
  /** When true, omit Workspace picker UI. Reserved for bar extensions. */
  hideWorkspace: _hideWorkspace = false,
}) {
  const queryClient = useQueryClient()

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
  const storeWorkspaceId = useAppStore((s) => s.activeWorkspaceId)
  const setActivePersonaId = useAppStore((s) => s.setActivePersonaId)

  const { data: modelsData, isLoading: modelsLoading } = useQuery({
    queryKey: ['inference', 'models'],
    queryFn: fetchModels,
    staleTime: 60_000,
  })

  const { data: modelSettings, isLoading: settingsLoading } = useQuery({
    queryKey: ['inference', 'settings'],
    queryFn: () => getModelSettings(),
    staleTime: 60_000,
  })

  const hiddenNames = useMemo(
    () => new Set(Array.isArray(modelSettings?.hidden_models) ? modelSettings.hidden_models : []),
    [modelSettings],
  )

  const { data: personaPack } = useQuery({
    queryKey: ['personas'],
    queryFn: () => listPersonas(),
    staleTime: 30_000,
  })
  const personas = personaPack?.items ?? []
  const defaultPersona = useMemo(() => {
    return personas.find((p) => p.is_default_808notes) ?? null
  }, [personas])

  const { data: chat } = useQuery({
    queryKey: ['chat', activeChatId],
    queryFn: () => getChat(activeChatId),
    enabled: Boolean(activeChatId),
  })

  const { data: workspacePack } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => listWorkspaces(),
    staleTime: 30_000,
  })
  const workspaces = workspacePack?.items ?? []

  const models = useMemo(() => {
    const raw = Array.isArray(modelsData?.data) ? modelsData.data : []
    return raw
      .map((m) => ({
        id: typeof m?.id === 'string' ? m.id : '',
        size: m?.size,
      }))
      .filter((m) => m.id && !hiddenNames.has(m.id))
  }, [modelsData, hiddenNames])

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase()
    if (!s) return models
    return models.filter((m) => m.id.toLowerCase().includes(s))
  }, [models, q])

  const sortedFiltered = useMemo(
    () => sortSelectedFirst(filtered, selectedModel, 'id'),
    [filtered, selectedModel],
  )

  const chatPersonaId = chat?.persona_id ?? null
  const chatWorkspaceId = chat?.workspace_id ?? null
  const effectivePersonaId = activeChatId ? chatPersonaId : storePersonaId
  const effectiveWorkspaceId = activeChatId ? chatWorkspaceId : storeWorkspaceId

  const displayPersona = useMemo(() => {
    if (effectivePersonaId) return personas.find((p) => p.id === effectivePersonaId) ?? defaultPersona
    return defaultPersona
  }, [effectivePersonaId, personas, defaultPersona])

  const displayWorkspace = useMemo(() => {
    if (!effectiveWorkspaceId) return null
    return workspaces.find((w) => w.id === effectiveWorkspaceId) ?? null
  }, [effectiveWorkspaceId, workspaces])

  const workspacePinnedModel = useMemo(
    () => (displayWorkspace?.model && String(displayWorkspace.model).trim()) || '',
    [displayWorkspace?.model],
  )
  const modelLocked = Boolean(
    workspacePinnedModel && (activeChatId ? chatWorkspaceId : storeWorkspaceId),
  )

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
    const v = String(modelSettings?.default_model ?? '').trim()
    setDefaultModel(v || null)
  }, [modelSettings?.default_model, setDefaultModel])

  useEffect(() => {
    if (!modelLocked || !workspacePinnedModel) return
    if (selectedModel !== workspacePinnedModel) setSelectedModel(workspacePinnedModel)
  }, [modelLocked, workspacePinnedModel, selectedModel, setSelectedModel])

  useEffect(() => {
    if (activeChatId != null) return
    if (modelLocked) return
    if (modelsLoading || settingsLoading) return
    if (!models.length) return
    if (userTouchedLandingModelRef.current) return
    const def = String(modelSettings?.default_model ?? '').trim()
    const pick = def && models.some((m) => m.id === def) ? def : models[0].id
    if (useAppStore.getState().selectedModel === pick) return
    setSelectedModel(pick)
  }, [
    activeChatId,
    modelsLoading,
    settingsLoading,
    models,
    modelSettings?.default_model,
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

  async function selectModel(modelId) {
    if (modelLocked) return
    if (!activeChatId) userTouchedLandingModelRef.current = true
    setSelectedModel(modelId)
    setModelOpen(false)
    setQ('')
    if (activeChatId) {
      try {
        await patchChat(activeChatId, { model: modelId })
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

  const displayName = (modelLocked ? workspacePinnedModel : selectedModel) || 'Select model'

  const showModelPicker = true
  const showPersonaPicker = true

  return (
    <div className={cn('flex min-w-0 flex-wrap items-center justify-center gap-2', className)}>
      {showModelPicker && (
      <div ref={modelWrapRef} className="relative">
        <span ref={modelBtnRef} className="inline-flex">
          <Button
            type="button"
            variant="ghost"
            disabled={modelLocked}
            title={modelLocked ? 'Model pinned by workspace (change on workspace detail page)' : undefined}
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
                  const sel = m.id === selectedModel
                  return (
                    <li key={m.id} className="min-w-0">
                      <button
                        type="button"
                        className={cn(
                          'flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors hover:bg-accent hover:text-accent-foreground',
                          sel && 'bg-muted',
                        )}
                        onClick={() => selectModel(m.id)}
                      >
                        <span className="size-8 shrink-0 rounded-full border border-border bg-muted" aria-hidden />
                        <span className="min-w-0 flex-1 truncate font-medium text-foreground">{m.id}</span>
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
      )}

      {!hidePersona && showPersonaPicker && (
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
                    <span className="truncate">Default ({defaultPersona?.name || 'Assistant'})</span>
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
