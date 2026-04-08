import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useParams } from 'react-router-dom'

import { addDawMemory, deleteDawMemory, getDawMemory, getStoredBoolabToken } from '@/api/index.js'
import {
  deleteContextFile,
  getDaw,
  getDawInstructions,
  listContextFiles,
  patchContextFile,
  pinDaw,
  putDawInstructions,
  updateDaw,
  uploadContextFile,
  uploadDawIcon,
} from '@/api/daws.js'
import { fetchOllamaModels } from '@/api/ollama.js'
import { Button } from '@/components/ui/button'
import { PATH_808NOTES, PATH_BOOOPS, is808notesRouteContext } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

const FALLBACK_CHAT_MODELS = [
  'llama-gpu/qwen3.5-9b-exl3',
  'qwen3.5:35b',
  'claude-sonnet',
  'claude-haiku',
  'claude-opus',
]

function EmbeddableSwitch({ embeddable, disabled, onToggle }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={embeddable}
      disabled={disabled}
      onClick={() => onToggle(!embeddable)}
      className="relative inline-flex h-6 w-10 shrink-0 rounded-full border border-border transition-colors disabled:opacity-50"
      style={{
        backgroundColor: embeddable ? 'var(--primary)' : 'var(--muted)',
      }}
    >
      <span
        className={cn(
          'pointer-events-none block size-5 translate-x-0.5 rounded-full shadow transition-transform',
          embeddable && 'translate-x-[1.15rem]',
        )}
        style={{ backgroundColor: 'var(--background)' }}
      />
    </button>
  )
}

export default function DawDetailPage() {
  const { id } = useParams()
  const { pathname } = useLocation()
  const storeMode = useAppStore((s) => s.mode)
  const routeBase = is808notesRouteContext(pathname, storeMode) ? PATH_808NOTES : PATH_BOOOPS
  const is808notesWorkspace = routeBase === PATH_808NOTES
  const queryClient = useQueryClient()
  const fileInputRef = useRef(null)
  const iconInputRef = useRef(null)

  const [nameEdit, setNameEdit] = useState('')
  const [nameEditing, setNameEditing] = useState(false)
  const [detailName, setDetailName] = useState('')
  const [detailDesc, setDetailDesc] = useState('')
  const [detailColor, setDetailColor] = useState('#7c3aed')
  const [detailTemp, setDetailTemp] = useState(0.7)
  const tempSaveTimerRef = useRef(null)
  const [inferModel, setInferModel] = useState('')
  const [inferMaxTok, setInferMaxTok] = useState(2048)
  const [inferTopP, setInferTopP] = useState(1)
  const [inferTopK, setInferTopK] = useState(20)
  const [inferCtx, setInferCtx] = useState(8192)
  const [ragMode, setRagMode] = useState('auto')
  const [instrDraft, setInstrDraft] = useState('')
  const [memoryDraft, setMemoryDraft] = useState('')
  const [syncFolder, setSyncFolder] = useState('')
  const [syncEnabled, setSyncEnabled] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState(null)

  const invalidateDaw = () => {
    queryClient.invalidateQueries({ queryKey: ['daws'] })
  }

  const { data: daw, isLoading, isError } = useQuery({
    queryKey: ['daws', id],
    queryFn: () => getDaw(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  const { data: ollamaData } = useQuery({
    queryKey: ['ollama', 'models'],
    queryFn: fetchOllamaModels,
    staleTime: 60_000,
  })

  const inferModelOptions = useMemo(() => {
    const raw = Array.isArray(ollamaData?.data) ? ollamaData.data : []
    const names = raw.map((m) => (typeof m?.id === 'string' ? m.id : '')).filter(Boolean)
    const set = new Set([...FALLBACK_CHAT_MODELS, ...names])
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [ollamaData])

  useEffect(() => {
    if (!daw) return
    setNameEdit(daw.name || '')
    setDetailName(daw.name || '')
    setDetailDesc(daw.description || '')
    setDetailColor(daw.color || '#7c3aed')
    const t = daw.temperature
    setDetailTemp(typeof t === 'number' && !Number.isNaN(t) ? t : 0.7)
    setInferModel((daw.model && String(daw.model).trim()) || '')
    const mt = daw.max_tokens
    setInferMaxTok(typeof mt === 'number' && !Number.isNaN(mt) ? mt : 2048)
    const tp = daw.top_p
    setInferTopP(typeof tp === 'number' && !Number.isNaN(tp) ? tp : 1)
    const tk = daw.top_k
    setInferTopK(typeof tk === 'number' && !Number.isNaN(tk) ? tk : 20)
    const cw = daw.context_window
    setInferCtx(typeof cw === 'number' && !Number.isNaN(cw) ? cw : 8192)
    const rm = daw.rag_mode
    setRagMode(rm === 'always' || rm === 'off' || rm === 'auto' ? rm : 'auto')
    setSyncFolder(daw.dubdrive_sync_folder || '')
    setSyncEnabled(Boolean(daw.dubdrive_sync_enabled))
  }, [daw])

  useEffect(() => {
    return () => {
      if (tempSaveTimerRef.current != null) clearTimeout(tempSaveTimerRef.current)
    }
  }, [])

  const { data: files = [] } = useQuery({
    queryKey: ['daw-context-files', id],
    queryFn: () => listContextFiles(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })
  const fileRows = Array.isArray(files) ? files : []

  const { data: instrPack } = useQuery({
    queryKey: ['daws', id, 'instructions'],
    queryFn: () => getDawInstructions(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  useEffect(() => {
    if (instrPack && typeof instrPack.content === 'string') setInstrDraft(instrPack.content)
  }, [instrPack])

  const { data: dawMemoryList = [], isError: dawMemoryError } = useQuery({
    queryKey: ['daws', id, 'memory'],
    queryFn: () => getDawMemory(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })
  const memoryRows = Array.isArray(dawMemoryList) ? dawMemoryList : []

  function formatMemoryDate(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const saveDetails = useMutation({
    mutationFn: () =>
      updateDaw(id, {
        name: detailName.trim() || 'Untitled',
        description: detailDesc.trim() || null,
        color: detailColor || '#7c3aed',
        dubdrive_sync_folder: syncFolder.trim() || null,
        dubdrive_sync_enabled: syncEnabled,
      }),
    onSuccess: () => invalidateDaw(),
  })

  async function triggerSync() {
    setSyncing(true)
    setSyncResult(null)
    try {
      const res = await fetch(`/api/dubdrive-sync/${id}/sync`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getStoredBoolabToken()}` },
      })
      const json = await res.json().catch(() => ({}))
      if (!res.ok) {
        setSyncResult({
          error:
            (typeof json?.detail === 'string' && json.detail) ||
            (typeof json?.message === 'string' && json.message) ||
            `Sync failed (${res.status})`,
        })
      } else {
        setSyncResult(json)
      }
    } catch {
      setSyncResult({ error: 'Sync failed' })
    } finally {
      setSyncing(false)
    }
  }

  const saveNameInline = useMutation({
    mutationFn: () => updateDaw(id, { name: nameEdit.trim() || 'Untitled' }),
    onSuccess: () => {
      setNameEditing(false)
      invalidateDaw()
    },
  })

  const uploadIconMut = useMutation({
    mutationFn: (file) => uploadDawIcon(id, file),
    onSuccess: () => invalidateDaw(),
  })

  const removeIconMut = useMutation({
    mutationFn: () => updateDaw(id, { icon_url: null }),
    onSuccess: () => invalidateDaw(),
  })

  const uploadFileMut = useMutation({
    mutationFn: (file) => uploadContextFile(id, file, false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daw-context-files', id] })
    },
  })

  const patchFileMut = useMutation({
    mutationFn: ({ fileId, embeddable }) => patchContextFile(fileId, { embeddable }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['daw-context-files', id] }),
  })

  const delFileMut = useMutation({
    mutationFn: (fileId) => deleteContextFile(fileId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['daw-context-files', id] }),
  })

  const saveInstr = useMutation({
    mutationFn: () => putDawInstructions(id, instrDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['daws', id, 'instructions'] }),
  })

  const addMemoryMut = useMutation({
    mutationFn: () => addDawMemory(id, memoryDraft.trim()),
    onSuccess: () => {
      setMemoryDraft('')
      queryClient.invalidateQueries({ queryKey: ['daws', id, 'memory'] })
    },
  })

  const delMemoryMut = useMutation({
    mutationFn: (entryId) => deleteDawMemory(id, entryId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['daws', id, 'memory'] }),
  })

  const pinMut = useMutation({
    mutationFn: ({ slot, pinned }) => pinDaw(id, slot, pinned),
    onSuccess: () => invalidateDaw(),
  })

  const patchTemperatureMut = useMutation({
    mutationFn: (temperature) => updateDaw(id, { temperature }),
    onSuccess: () => invalidateDaw(),
  })

  const patchTopKMut = useMutation({
    mutationFn: (top_k) => updateDaw(id, { top_k }),
    onSuccess: () => invalidateDaw(),
  })

  function scheduleTemperatureSave(next) {
    setDetailTemp(next)
    if (tempSaveTimerRef.current != null) clearTimeout(tempSaveTimerRef.current)
    tempSaveTimerRef.current = setTimeout(() => {
      tempSaveTimerRef.current = null
      patchTemperatureMut.mutate(next)
    }, 350)
  }

  const saveInferMut = useMutation({
    mutationFn: () => {
      const payload = {
        model: inferModel.trim() || null,
        max_tokens: inferMaxTok,
        top_p: inferTopP,
        top_k: inferTopK,
        context_window: inferCtx,
      }
      if (!is808notesWorkspace) {
        payload.rag_mode = ragMode
      }
      return updateDaw(id, payload)
    },
    onSuccess: () => invalidateDaw(),
  })

  if (!id) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Missing DAW id.{' '}
        <Link to={`${routeBase}/daws`}>Back</Link>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <div className="border-b border-border px-4 py-4">
        <Link to={`${routeBase}/daws`} className="text-sm text-muted-foreground hover:text-foreground">
          ← DAWs
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className="size-3 shrink-0 rounded-full"
            style={{ background: daw?.color || '#7c3aed' }}
            aria-hidden
          />
          {nameEditing ? (
            <div className="flex flex-wrap items-center gap-2">
              <input
                value={nameEdit}
                onChange={(e) => setNameEdit(e.target.value)}
                className="h-9 min-w-[12rem] rounded-md border border-border bg-background px-2 text-lg font-semibold text-foreground outline-none ring-ring focus-visible:ring-2"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveNameInline.mutate()
                  if (e.key === 'Escape') {
                    setNameEditing(false)
                    setNameEdit(daw?.name || '')
                  }
                }}
              />
              <Button type="button" size="sm" onClick={() => saveNameInline.mutate()} disabled={saveNameInline.isPending}>
                Save
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setNameEditing(false)
                  setNameEdit(daw?.name || '')
                }}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <button
              type="button"
              className="text-left text-lg font-semibold tracking-tight text-foreground hover:underline"
              onClick={() => {
                setNameEdit(daw?.name || '')
                setNameEditing(true)
              }}
            >
              {isLoading ? '…' : daw?.name || 'DAW'}
            </button>
          )}
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {isError && <p className="text-sm text-destructive">DAW not found.</p>}

        {daw && (
          <>
            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Details</h2>
              <div className="flex flex-col gap-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Name</span>
                  <input
                    value={detailName}
                    onChange={(e) => setDetailName(e.target.value)}
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Description</span>
                  <textarea
                    value={detailDesc}
                    onChange={(e) => setDetailDesc(e.target.value)}
                    rows={4}
                    className="resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Color</span>
                  <input
                    type="color"
                    value={detailColor}
                    onChange={(e) => setDetailColor(e.target.value)}
                    className="h-9 w-24 cursor-pointer rounded-md border border-border bg-background"
                  />
                </label>
                <div className="flex flex-col gap-2 text-sm">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Temperature</span>
                    <span className="tabular-nums text-foreground">{detailTemp.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={2}
                    step={0.05}
                    value={detailTemp}
                    onChange={(e) => scheduleTemperatureSave(Number(e.target.value))}
                    disabled={patchTemperatureMut.isPending}
                    className="h-2 w-full cursor-pointer accent-primary disabled:opacity-50"
                    aria-valuemin={0}
                    aria-valuemax={2}
                    aria-valuenow={detailTemp}
                  />
                  <p className="text-xs text-muted-foreground">
                    Lower values are more deterministic. Used for Ollama; Claude uses the same setting clamped to 0–1.
                  </p>
                </div>
                <Button type="button" size="sm" onClick={() => saveDetails.mutate()} disabled={saveDetails.isPending}>
                  Save
                </Button>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Model and generation</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Optional pinned model for this DAW. When set, chat uses these parameters and the model cannot be changed
                from the chat bar. Leave as “Global default” to use the DAW model picker and global context window.
              </p>
              <div className="flex flex-col gap-4 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-muted-foreground">Model</span>
                  <select
                    value={inferModel}
                    onChange={(e) => setInferModel(e.target.value)}
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                  >
                    <option value="">Global default (DAW model picker)</option>
                    {inferModelOptions.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Max tokens</span>
                    <span className="tabular-nums text-foreground">{inferMaxTok}</span>
                  </div>
                  <input
                    type="range"
                    min={512}
                    max={4096}
                    step={256}
                    value={inferMaxTok}
                    onChange={(e) => setInferMaxTok(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Top-p</span>
                    <span className="tabular-nums text-foreground">{inferTopP.toFixed(1)}</span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.1}
                    value={inferTopP}
                    onChange={(e) => setInferTopP(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Top-k</span>
                    <span className="tabular-nums text-foreground">{inferTopK}</span>
                  </div>
                  <input
                    type="range"
                    min={1}
                    max={100}
                    step={1}
                    value={inferTopK}
                    onChange={(e) => setInferTopK(Number(e.target.value))}
                    onMouseUp={(e) => patchTopKMut.mutate(Number(e.currentTarget.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                  <p className="text-xs text-muted-foreground">
                    Limits token sampling to the top K candidates. Lower = more focused. Ollama only.
                  </p>
                </div>
                <div className="flex flex-col gap-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-muted-foreground">Context window</span>
                    <span className="tabular-nums text-foreground">{inferCtx}</span>
                  </div>
                  <input
                    type="range"
                    min={1024}
                    max={32768}
                    step={1024}
                    value={inferCtx}
                    onChange={(e) => setInferCtx(Number(e.target.value))}
                    className="h-2 w-full cursor-pointer accent-primary"
                  />
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-muted-foreground">RAG Mode</span>
                  <select
                    value={is808notesWorkspace ? 'always' : ragMode}
                    onChange={(e) => setRagMode(e.target.value)}
                    disabled={is808notesWorkspace || saveInferMut.isPending}
                    title={is808notesWorkspace ? '808notes always uses RAG' : undefined}
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <option value="auto">Auto (intent gate)</option>
                    <option value="always">Always</option>
                    <option value="off">Off</option>
                  </select>
                </label>
                {is808notesWorkspace ? (
                  <p className="text-xs text-muted-foreground">808notes always uses RAG.</p>
                ) : null}
                <Button type="button" size="sm" onClick={() => saveInferMut.mutate()} disabled={saveInferMut.isPending}>
                  Save inference settings
                </Button>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Icon</h2>
              <div className="flex flex-col gap-3">
                {daw.icon_url ? (
                  <img src={daw.icon_url} alt="" className="size-16 rounded-full object-cover" />
                ) : (
                  <p className="text-sm text-muted-foreground">No icon</p>
                )}
                <input
                  ref={iconInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    e.target.value = ''
                    if (f) uploadIconMut.mutate(f)
                  }}
                />
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() => iconInputRef.current?.click()}
                    disabled={uploadIconMut.isPending}
                  >
                    {uploadIconMut.isPending ? 'Uploading…' : 'Upload image'}
                  </Button>
                  {daw.icon_url ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => removeIconMut.mutate()}
                      disabled={removeIconMut.isPending}
                    >
                      Remove icon
                    </Button>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-medium text-foreground">Context files</h2>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    e.target.value = ''
                    if (f) uploadFileMut.mutate(f)
                  }}
                />
                <Button
                  type="button"
                  size="sm"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadFileMut.isPending}
                >
                  {uploadFileMut.isPending ? 'Uploading…' : 'Upload file'}
                </Button>
              </div>
              {fileRows.length === 0 ? (
                <p className="text-sm text-muted-foreground">No context files</p>
              ) : (
                <ul className="flex flex-col gap-3">
                  {fileRows.map((f) => (
                    <li
                      key={f.id}
                      className="flex flex-col gap-2 rounded-md border border-border/60 px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-foreground">{f.filename}</p>
                        <p className="line-clamp-2 text-xs text-muted-foreground">{f.content_preview || '—'}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-3">
                        <EmbeddableSwitch
                          embeddable={f.embeddable === true}
                          disabled={patchFileMut.isPending}
                          onToggle={(next) => patchFileMut.mutate({ fileId: f.id, embeddable: next })}
                        />
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          onClick={() => delFileMut.mutate(f.id)}
                          disabled={delFileMut.isPending}
                        >
                          Delete
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Instructions</h2>
              <textarea
                value={instrDraft}
                onChange={(e) => setInstrDraft(e.target.value)}
                rows={8}
                className="mb-3 w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
              />
              <Button type="button" size="sm" onClick={() => saveInstr.mutate()} disabled={saveInstr.isPending}>
                Save
              </Button>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">DAW Memory</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Entries are injected into every conversation in this DAW.
              </p>
              {dawMemoryError ? (
                <p className="text-sm text-muted-foreground">Memory is only available to the site owner.</p>
              ) : memoryRows.length === 0 ? (
                <p className="mb-3 text-sm text-muted-foreground">No memory entries yet.</p>
              ) : (
                <ul className="mb-4 flex flex-col gap-3">
                  {memoryRows.map((entry) => (
                    <li
                      key={entry.id}
                      className="flex flex-col gap-1 rounded-md border border-border/60 px-3 py-2 sm:flex-row sm:items-start sm:justify-between"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="whitespace-pre-wrap break-words text-sm text-foreground">{entry.content}</p>
                        <p className="text-xs text-muted-foreground">{formatMemoryDate(entry.created_at)}</p>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="shrink-0 self-end sm:self-start"
                        onClick={() => delMemoryMut.mutate(entry.id)}
                        disabled={delMemoryMut.isPending}
                      >
                        Delete
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="flex flex-col gap-2">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">New entry</span>
                  <textarea
                    value={memoryDraft}
                    onChange={(e) => setMemoryDraft(e.target.value)}
                    rows={3}
                    maxLength={2000}
                    className="w-full resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                  />
                </label>
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    {memoryDraft.length} / 2000
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => addMemoryMut.mutate()}
                    disabled={
                      addMemoryMut.isPending ||
                      !memoryDraft.trim() ||
                      memoryDraft.trim().length > 2000
                    }
                  >
                    Add Memory
                  </Button>
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">DubDrive Sync</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Folder on DubDrive to scan for files. When auto-sync is on and you run sync, new files are ingested into
                this DAW&apos;s sources.
              </p>
              <div className="flex flex-col gap-3 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-muted-foreground">Sync folder path</span>
                  <input
                    type="text"
                    value={syncFolder}
                    onChange={(e) => setSyncFolder(e.target.value)}
                    placeholder="/HomeLabRepos/boolab"
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                  />
                </label>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-foreground">Auto-sync enabled</span>
                  <EmbeddableSwitch embeddable={syncEnabled} disabled={false} onToggle={setSyncEnabled} />
                </div>
                <Button type="button" size="sm" onClick={triggerSync} disabled={syncing || !syncFolder.trim()}>
                  {syncing ? 'Syncing…' : 'Sync now'}
                </Button>
                {syncResult ? (
                  <p className="text-sm text-muted-foreground" role="status">
                    {syncResult.error != null
                      ? String(syncResult.error)
                      : `Queued ${syncResult.queued}, skipped ${syncResult.skipped} of ${syncResult.total_found}`}
                  </p>
                ) : null}
                <p className="text-xs text-muted-foreground">
                  Persist folder path and auto-sync with <span className="text-foreground">Save</span> in Details above.
                </p>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Pin settings</h2>
              <ul className="flex flex-col gap-3">
                <li className="flex items-center justify-between gap-3">
                  <span className="text-sm text-foreground">Pin in BooOps sidebar</span>
                  <EmbeddableSwitch
                    embeddable={daw.pinned_booops === true}
                    disabled={pinMut.isPending}
                    onToggle={(next) => pinMut.mutate({ slot: 'booops', pinned: next })}
                  />
                </li>
                <li className="flex items-center justify-between gap-3">
                  <span className="text-sm text-foreground">Pin in 808notes sidebar</span>
                  <EmbeddableSwitch
                    embeddable={daw.pinned_808notes === true}
                    disabled={pinMut.isPending}
                    onToggle={(next) => pinMut.mutate({ slot: '808notes', pinned: next })}
                  />
                </li>
              </ul>
            </section>
          </>
        )}
      </div>
    </div>
  )
}
