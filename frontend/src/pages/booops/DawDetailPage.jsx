import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useParams } from 'react-router-dom'

import {
  addDawMemory,
  clearDawEmbeddings,
  deleteDawMemory,
  getDawMemory,
  getStoredBoolabToken,
} from '@/api/index.js'
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
import { listSkills, getDawSkills, addSkillToDaw, removeSkillFromDaw, toggleDawSkill } from '@/api/skills'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
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
  const [inferModel, setInferModel] = useState('')
  const [ragMode, setRagMode] = useState('auto')
  const [instrDraft, setInstrDraft] = useState('')
  const [memoryDraft, setMemoryDraft] = useState('')
  const [syncFolder, setSyncFolder] = useState('')
  const [syncEnabled, setSyncEnabled] = useState(false)
  const [pinned808notes, setPinned808notes] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState(null)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [skillsAddDialogOpen, setSkillsAddDialogOpen] = useState(false)

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
    setInferModel((daw.model && String(daw.model).trim()) || '')
    const rm = daw.rag_mode
    setRagMode(rm === 'always' || rm === 'off' || rm === 'auto' ? rm : 'auto')
    setSyncFolder(daw.dubdrive_sync_folder || '')
    setSyncEnabled(Boolean(daw.dubdrive_sync_enabled))
    setPinned808notes(Boolean(daw.pinned_808notes))
  }, [daw])

  useEffect(() => {
    return () => {}
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

  const { data: dawSkillsList = [] } = useQuery({
    queryKey: ['daws', id, 'skills'],
    queryFn: () => getDawSkills(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  const { data: allSkills = [] } = useQuery({
    queryKey: ['skills'],
    queryFn: listSkills,
    staleTime: 30_000,
  })

  const attachSkillMutation = useMutation({
    mutationFn: ({ skillId, active }) => addSkillToDaw(id, skillId, active),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daws', id, 'skills'] })
    },
  })

  const detachSkillMutation = useMutation({
    mutationFn: (skillId) => removeSkillFromDaw(id, skillId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daws', id, 'skills'] })
    },
  })

  const toggleSkillMutation = useMutation({
    mutationFn: ({ skillId, active }) => toggleDawSkill(id, skillId, active),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daws', id, 'skills'] })
    },
  })

  const attachedSkillIds = new Set(dawSkillsList.map(s => s.id))
  const unattachedSkills = allSkills.filter(s => !attachedSkillIds.has(s.id))

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
        pinned_808notes: pinned808notes,
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

const saveInferMut = useMutation({
      mutationFn: () => {
        const payload = {
          model: inferModel.trim() || null,
        }
        if (!is808notesWorkspace) {
          payload.rag_mode = ragMode
        }
        return updateDaw(id, payload)
      },
      onSuccess: () => invalidateDaw(),
    })

  const clearEmbeddingsMut = useMutation({
    mutationFn: () => clearDawEmbeddings(id),
    onSuccess: () => {
      invalidateDaw()
      setShowClearConfirm(false)
      setClearing(false)
    },
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
                     <div>
                       <input
                         type="color"
                         value={detailColor}
                         onChange={(e) => setDetailColor(e.target.value)}
                         className="h-9 w-24 cursor-pointer rounded-md border border-border bg-background"
                       />
                     </div>
                   </label>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm text-foreground">Pin to 808notes sidebar</span>
                    <EmbeddableSwitch embeddable={pinned808notes} disabled={false} onToggle={setPinned808notes} />
                  </div>
                  <Button type="button" size="sm" onClick={() => saveDetails.mutate()} disabled={saveDetails.isPending}>
                    Save
                  </Button>
              </div>
             </section>
            
            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Model and generation</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                 Optional pinned model for this DAW. Leave as "Global default" to use the DAW model picker.
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
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-medium text-foreground">Skills</h2>
                <Button type="button" size="sm" onClick={() => setSkillsAddDialogOpen(true)}>
                  <Plus className="mr-1 h-3 w-3" />
                  Add from Library
                </Button>
              </div>
              <p className="mb-3 text-xs text-muted-foreground">
                AI skills attached to this DAW are injected into every conversation.
              </p>
              {dawSkillsList.length === 0 ? (
                <p className="mb-3 text-sm text-muted-foreground">No skills attached yet.</p>
              ) : (
                <ul className="mb-4 flex flex-col gap-2">
                  {dawSkillsList.map((skill) => (
                    <li
                      key={skill.id}
                      className="flex items-start justify-between gap-3 rounded-md border border-border/60 px-3 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm text-foreground">{skill.name}</span>
                          {skill.active && (
                            <Badge variant="default" className="h-5 px-1.5 text-[10px]">Active</Badge>
                          )}
                        </div>
                        {skill.description && (
                          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{skill.description}</p>
                        )}
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => toggleSkillMutation.mutate({ skillId: skill.id, active: !skill.active })}
                          disabled={toggleSkillMutation.isPending}
                          title={skill.active ? 'Deactivate' : 'Activate'}
                        >
                          {skill.active ? '✓' : '○'}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="ghost"
                          onClick={() => detachSkillMutation.mutate(skill.id)}
                          disabled={detachSkillMutation.isPending}
                          title="Remove"
                        >
                          <X className="h-3.5 w-3.5 text-destructive" />
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}

              {/* Add Skill Dialog */}
              <Dialog open={skillsAddDialogOpen} onOpenChange={setSkillsAddDialogOpen}>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Add Skill to DAW</DialogTitle>
                    <DialogDescription>
                      Choose a skill from your library to attach to this DAW.
                    </DialogDescription>
                  </DialogHeader>
                  {unattachedSkills.length === 0 ? (
                    <p className="text-sm text-muted-foreground">No skills available in library.</p>
                  ) : (
                    <div className="max-h-64 overflow-y-auto space-y-2">
                      {unattachedSkills.map((skill) => (
                        <div
                          key={skill.id}
                          className="flex items-start justify-between gap-2 rounded-md border border-border p-2 hover:bg-muted/50"
                        >
                          <div className="min-w-0 flex-1">
                            <div className="font-medium text-sm">{skill.name}</div>
                            {skill.description && (
                              <div className="line-clamp-2 text-xs text-muted-foreground">{skill.description}</div>
                            )}
                          </div>
                          <Button
                            type="button"
                            size="sm"
                            onClick={() => {
                              attachSkillMutation.mutate({ skillId: skill.id, active: true })
                              setSkillsAddDialogOpen(false)
                            }}
                            disabled={attachSkillMutation.isPending}
                          >
                            Add
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </DialogContent>
              </Dialog>
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

            <section className="rounded-lg border border-destructive bg-destructive/5 p-4">
              <h2 className="mb-3 text-sm font-medium text-destructive">Danger zone</h2>
              <p className="mb-4 text-xs text-muted-foreground">
                Irreversible actions that affect this DAW&apos;s embeddings and sources.
              </p>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm">
                  <span className="font-medium text-foreground">Clear Embeddings</span>
                  <p className="text-xs text-muted-foreground">
                    Delete all chunks and reset sources to pending. Re-sync required.
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  onClick={() => setShowClearConfirm(true)}
                  disabled={clearing || clearEmbeddingsMut.isPending}
                >
                  {clearing || clearEmbeddingsMut.isPending ? 'Clearing…' : 'Clear Embeddings'}
                </Button>
              </div>
            </section>
          </>
        )}
      </div>

      {showClearConfirm ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-lg">
            <h3 className="mb-2 text-lg font-semibold text-foreground">Clear Embeddings?</h3>
            <p className="mb-4 text-sm text-muted-foreground">
              This will delete all chunks and embeddings for this DAW. Sources will need to be re-synced.
              Continue?
            </p>
            <div className="flex flex-wrap justify-end gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowClearConfirm(false)
                  setClearing(false)
                }}
                disabled={clearing || clearEmbeddingsMut.isPending}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                onClick={() => {
                  setClearing(true)
                  clearEmbeddingsMut.mutate()
                }}
                disabled={clearing || clearEmbeddingsMut.isPending}
              >
                {clearing || clearEmbeddingsMut.isPending ? 'Clearing…' : 'Clear'}
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
