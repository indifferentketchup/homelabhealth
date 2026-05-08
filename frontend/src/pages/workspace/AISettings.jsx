import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { getCustomInstructions, putCustomInstructions } from '@/api/customInstructions.js'
import { getModelServerConfig, patchModelServerConfig } from '@/api/settings.js'
import { embedAllMemories, extractMemory, getMemory, putMemory } from '@/api/memory.js'
import { createMemoryEntry, deleteMemoryEntry, listMemoryEntries } from '@/api/memoryEntries.js'
import { fetchModels, getModelSettings, patchModelSettings } from '@/api/inference.js'
import { createPersona, deletePersona, listPersonas, updatePersona, uploadPersonaIcon } from '@/api/personas.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store/index.js'

function WorkspaceModelsSection({ queryClient, selectClass }) {
  const {
    data: modelsData,
    isLoading: modelsLoading,
    isError: modelsError,
  } = useQuery({
    queryKey: ['inference', 'models'],
    queryFn: fetchModels,
    staleTime: 60_000,
    retry: false,
  })

  const { data: modelSettings } = useQuery({
    queryKey: ['inference', 'settings'],
    queryFn: () => getModelSettings(),
    staleTime: 30_000,
  })

  const modelEntries = useMemo(() => {
    const raw = Array.isArray(modelsData?.data) ? modelsData.data : []
    return raw
      .map((m) => ({
        id: typeof m?.id === 'string' ? m.id : '',
      }))
      .filter((m) => m.id)
  }, [modelsData])

  const hiddenSet = useMemo(
    () => new Set(Array.isArray(modelSettings?.hidden_models) ? modelSettings.hidden_models : []),
    [modelSettings],
  )

  async function onDefaultModelChange(value) {
    try {
      const out = await patchModelSettings({ default_model: value })
      queryClient.setQueryData(['inference', 'settings'], out)
    } catch {
      /* ignore */
    }
  }

  async function setModelVisibility(modelId, visible) {
    const current = Array.isArray(modelSettings?.hidden_models) ? [...modelSettings.hidden_models] : []
    let next
    if (visible) {
      next = current.filter((h) => h !== modelId)
    } else if (!current.includes(modelId)) {
      next = [...current, modelId]
    } else {
      next = current
    }
    try {
      const out = await patchModelSettings({ hidden_models: next })
      queryClient.setQueryData(['inference', 'settings'], out)
    } catch {
      /* ignore */
    }
  }

  const defaultModel = useMemo(() => {
    const api = String(modelSettings?.default_model ?? '').trim()
    if (api && modelEntries.some((m) => m.id === api)) return api
    return modelEntries[0]?.id ?? api
  }, [modelSettings?.default_model, modelEntries])

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-sm font-medium text-foreground">Models</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          OpenAI-compatible inference. Default model applies to this app.
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">Default model</h3>
        {modelsError ? (
          <p className="text-sm text-muted-foreground">Inference backend unavailable</p>
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
                <option key={m.id} value={m.id}>
                  {m.id}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
        <h3 className="text-sm font-medium text-foreground">Visible models</h3>
        {modelsError ? (
          <p className="text-sm text-muted-foreground">Inference backend unavailable</p>
        ) : modelsLoading ? (
          <p className="text-sm text-muted-foreground">Loading models…</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {modelEntries.map((m) => {
              const visible = !hiddenSet.has(m.id)
              return (
                <li
                  key={m.id}
                  className={cn(
                    'flex items-center justify-between gap-3 rounded-md px-2 py-2',
                    visible && 'bg-accent/30',
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <span className="text-sm font-medium text-foreground">{m.id}</span>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={visible}
                    aria-label={visible ? `Hide ${m.id}` : `Show ${m.id}`}
                    onClick={() => void setModelVisibility(m.id, !visible)}
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
    </section>
  )
}

export default function AISettings() {
  const queryClient = useQueryClient()
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setActivePersonaId = useAppStore((s) => s.setActivePersonaId)
  const currentDefaultKey = 'is_default'
  const [tab, setTab] = useState('personas')

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
    queryKey: ['memory'],
    queryFn: () => getMemory(),
    enabled: tab === 'memory',
    staleTime: 15_000,
  })

  const [memDraft, setMemDraft] = useState('')
  useEffect(() => {
    if (memoryRow && typeof memoryRow.content === 'string') setMemDraft(memoryRow.content)
  }, [memoryRow])

  const saveMem = useMutation({
    mutationFn: () => putMemory(memDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['memory'] }),
  })

  const extractMem = useMutation({
    mutationFn: () => extractMemory(),
    onSuccess: (r) => {
      if (r?.content != null) setMemDraft(r.content)
      queryClient.invalidateQueries({ queryKey: ['memory'] })
    },
  })

  const { data: entriesRaw } = useQuery({
    queryKey: ['memory', 'entries'],
    queryFn: () => listMemoryEntries(),
    enabled: tab === 'memory',
    staleTime: 15_000,
  })
  const memoryEntries = Array.isArray(entriesRaw) ? entriesRaw : []

  const { data: globalInstrRow } = useQuery({
    queryKey: ['custom-instructions'],
    queryFn: () => getCustomInstructions(),
    enabled: tab === 'instructions',
    staleTime: 15_000,
  })

  const [gInstrDraft, setGInstrDraft] = useState('')
  useEffect(() => {
    if (globalInstrRow && typeof globalInstrRow.content === 'string') setGInstrDraft(globalInstrRow.content)
  }, [globalInstrRow])

  const [entryAdding, setEntryAdding] = useState(false)
  const [entryNewContent, setEntryNewContent] = useState('')
  const [expandedFactIds, setExpandedFactIds] = useState(() => new Set())
  const [embedResultMsg, setEmbedResultMsg] = useState(null)

  useEffect(() => {
    if (!embedResultMsg) return
    const t = window.setTimeout(() => setEmbedResultMsg(null), 5000)
    return () => window.clearTimeout(t)
  }, [embedResultMsg])

  const saveGlobalInstr = useMutation({
    mutationFn: () => putCustomInstructions(gInstrDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['custom-instructions'] }),
  })

  const addEntry = useMutation({
    mutationFn: () => createMemoryEntry(entryNewContent.trim()),
    onSuccess: () => {
      setEntryAdding(false)
      setEntryNewContent('')
      queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] })
    },
  })
  const delEntry = useMutation({
    mutationFn: (id) => deleteMemoryEntry(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] }),
  })
  const embedAllMut = useMutation({
    mutationFn: () => embedAllMemories(),
    onSuccess: (r) => {
      const embedded = typeof r?.embedded === 'number' ? r.embedded : 0
      const total = typeof r?.total === 'number' ? r.total : embedded
      setEmbedResultMsg(`Re-embedded ${embedded} of ${total} pending fact(s).`)
      queryClient.invalidateQueries({ queryKey: ['memory', 'entries'] })
    },
    onError: (e) => {
      setEmbedResultMsg(e instanceof Error ? e.message : String(e))
    },
  })

  function toggleFactExpanded(id) {
    setExpandedFactIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
    mutationFn: (id) => updatePersona(id, { [currentDefaultKey]: true }),
    onSuccess: async () => {
      await invalidatePersonas()
      const def = useAppStore.getState().personas.find((p) => p[currentDefaultKey])
      if (def) setActivePersonaId(def.id)
    },
  })

  const delPersona = useMutation({
    mutationFn: (id) => deletePersona(id),
    onSuccess: () => invalidatePersonas(),
  })

  const { data: modelServerConfig } = useQuery({
    queryKey: ['settings', 'inference'],
    queryFn: getModelServerConfig,
    enabled: tab === 'model',
    staleTime: 15_000,
  })
  const [ollFlash, setOllFlash] = useState(true)
  const [ollMaxLoaded, setOllMaxLoaded] = useState(1)
  const [ollKeepAlive, setOllKeepAlive] = useState('30m')
  useEffect(() => {
    if (!modelServerConfig) return
    if (typeof modelServerConfig.flash_attention === 'boolean') setOllFlash(modelServerConfig.flash_attention)
    const ml = modelServerConfig.max_loaded_models
    if (typeof ml === 'number' && !Number.isNaN(ml)) setOllMaxLoaded(ml)
    if (typeof modelServerConfig.keep_alive === 'string') setOllKeepAlive(modelServerConfig.keep_alive)
  }, [modelServerConfig])

  const saveModelServerConfigMut = useMutation({
    mutationFn: () =>
      patchModelServerConfig({
        flash_attention: ollFlash,
        max_loaded_models: ollMaxLoaded,
        keep_alive: ollKeepAlive.trim() || '30m',
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['settings', 'inference'] }),
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <div className="border-b border-border px-4 py-4">
        <h1 className="text-lg font-semibold tracking-tight text-foreground">AI</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Personas, memory, model defaults, and global instructions.
        </p>
        <div className="mt-4 flex gap-1 border-b border-border">
          {[
            { id: 'personas', label: 'Personas' },
            { id: 'memory', label: 'Memory' },
            { id: 'model', label: 'Model' },
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
                        {p[currentDefaultKey] && (
                          <span className="rounded-full bg-secondary px-2 py-0.5 text-xs font-medium text-secondary-foreground">
                            Default
                          </span>
                        )}
                      </div>
                      <p className="mt-2 line-clamp-3 text-sm text-muted-foreground">{p.system_prompt || '—'}</p>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2">
                      <Button type="button" size="sm" variant="secondary" onClick={() => openEditPersona(p)}>
                        Edit
                      </Button>
                      {!p[currentDefaultKey] && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => setDefaultPersona.mutate(p.id)}
                          disabled={setDefaultPersona.isPending}
                        >
                          Set default
                        </Button>
                      )}
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={p[currentDefaultKey]}
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
            <div className="space-y-3 rounded-lg border border-border bg-card/40 p-4">
              <div className="flex flex-wrap items-center justify-end gap-3">
                <div className="flex flex-wrap gap-2">
                  <Button type="button" size="sm" variant="secondary" onClick={() => setEntryAdding((a) => !a)}>
                    Add fact
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={embedAllMut.isPending}
                    onClick={() => embedAllMut.mutate()}
                  >
                    {embedAllMut.isPending ? 'Re-embedding…' : 'Re-embed all'}
                  </Button>
                </div>
              </div>
              {embedResultMsg ? (
                <p
                  className={cn(
                    'text-sm',
                    embedAllMut.isError ? 'text-destructive' : 'text-muted-foreground',
                  )}
                  role="status"
                >
                  {embedResultMsg}
                </p>
              ) : null}
              {entryAdding ? (
                <div className="rounded-lg border border-border bg-card p-4">
                  <label className="flex flex-col gap-1 text-sm">
                    <span className="text-muted-foreground">New fact</span>
                    <textarea
                      value={entryNewContent}
                      onChange={(e) => setEntryNewContent(e.target.value)}
                      rows={4}
                      className="w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                      placeholder="Something to remember…"
                    />
                  </label>
                  <div className="mt-3 flex flex-wrap gap-2">
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
              ) : null}
              {memoryEntries.length === 0 && !entryAdding ? (
                <p className="text-sm text-muted-foreground">
                  No memory facts stored. Facts are saved automatically when you use &apos;remember that&apos; in chat,
                  or add them manually here.
                </p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {memoryEntries.map((e) => {
                    const full = e.content || ''
                    const isLong = full.length > 120
                    const display =
                      expandedFactIds.has(e.id) || !isLong ? full : `${full.slice(0, 120)}…`
                    const hasEmb = e.has_embedding === true
                    const meta = (
                      <>
                        <p className="whitespace-pre-wrap text-sm text-foreground">{display}</p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2">
                          <span
                            className={cn(
                              'inline-block rounded-full px-2 py-0.5 text-xs font-medium',
                              e.source === 'auto'
                                ? 'bg-secondary text-secondary-foreground'
                                : 'bg-primary/15 text-foreground',
                            )}
                          >
                            {e.source === 'auto' ? 'auto' : 'manual'}
                          </span>
                          <span
                            className="flex items-center gap-1.5 text-xs text-muted-foreground"
                            title={hasEmb ? 'Has vector embedding' : 'No embedding yet'}
                          >
                            <span
                              className={cn('size-2 shrink-0 rounded-full', hasEmb ? 'bg-primary' : 'bg-muted-foreground/45')}
                              aria-hidden
                            />
                            <span className="sr-only">{hasEmb ? 'Embedded' : 'Not embedded'}</span>
                          </span>
                        </div>
                      </>
                    )
                    return (
                      <li
                        key={e.id}
                        className="flex items-start gap-1 rounded-md border border-border bg-card px-3 py-2.5"
                      >
                        {isLong ? (
                          <button
                            type="button"
                            className="min-w-0 flex-1 rounded-sm text-left outline-none ring-ring focus-visible:ring-2"
                            onClick={() => toggleFactExpanded(e.id)}
                          >
                            {meta}
                          </button>
                        ) : (
                          <div className="min-w-0 flex-1">{meta}</div>
                        )}
                        <button
                          type="button"
                          className="shrink-0 rounded px-2 py-1 text-lg leading-none text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                          aria-label="Delete fact"
                          disabled={delEntry.isPending}
                          onClick={() => delEntry.mutate(e.id)}
                        >
                          ×
                        </button>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>

            <div className="flex flex-col gap-3 border-t border-border pt-6">
              <div>
                <h2 className="text-sm font-medium text-foreground">Markdown memory</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Long-form notes (separate from the searchable facts above). Last updated applies to this editor only.
                </p>
              </div>
              {memoryRow?.updated_at && (
                <p className="text-xs text-muted-foreground">Last updated: {memoryRow.updated_at}</p>
              )}
              {memLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
              <textarea
                value={memDraft}
                onChange={(e) => setMemDraft(e.target.value)}
                rows={14}
                className="min-h-[10rem] w-full resize-y rounded-md border border-border bg-card px-3 py-2 font-mono text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
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
          </div>
        )}

        {tab === 'model' && (
          <div className="flex flex-col gap-6">
            <WorkspaceModelsSection
              queryClient={queryClient}
              selectClass="h-9 w-full max-w-md rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
            />
            <div className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-2 text-sm font-medium text-foreground">Model Server Configuration</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Changes apply on next inference server restart.
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
                  onClick={() => saveModelServerConfigMut.mutate()}
                  disabled={saveModelServerConfigMut.isPending}
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
          </div>
        )}
      </div>
    </div>
  )
}
