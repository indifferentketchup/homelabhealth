import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'

import {
  addWorkspaceMemory,
  clearWorkspaceEmbeddings,
  deleteWorkspaceMemory,
  getWorkspaceMemory,
} from '@/api/index.js'
import {
  deleteContextFile,
  getWorkspace,
  getWorkspaceInstructions,
  listContextFiles,
  patchContextFile,
  pinWorkspace,
  putWorkspaceInstructions,
  updateWorkspace,
  uploadContextFile,
  uploadWorkspaceIcon,
} from '@/api/workspaces.js'
import { fetchModels, getModelSettings } from '@/api/inference.js'
import {
  listSkills,
  getWorkspaceSkills,
  addSkillToWorkspace,
  removeSkillFromWorkspace,
  toggleWorkspaceSkill,
} from '@/api/skills'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'
import { Plus, X } from 'lucide-react'

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

export default function WorkspaceDetailPage() {
  const { id } = useParams()
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
  const [pinnedFlag, setPinnedFlag] = useState(false)
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [skillsAddDialogOpen, setSkillsAddDialogOpen] = useState(false)
  const invalidateWorkspace = () => {
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const { data: workspace, isLoading, isError } = useQuery({
    queryKey: ['workspaces', id],
    queryFn: () => getWorkspace(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  const { data: modelsData } = useQuery({
    queryKey: ['inference', 'models'],
    queryFn: fetchModels,
    staleTime: 60_000,
  })

  const { data: modelSettings } = useQuery({
    queryKey: ['inference', 'settings'],
    queryFn: () => getModelSettings(),
    staleTime: 60_000,
  })

  const hiddenNames = useMemo(
    () => new Set(Array.isArray(modelSettings?.hidden_models) ? modelSettings.hidden_models : []),
    [modelSettings],
  )

  const inferModelOptions = useMemo(() => {
    const raw = Array.isArray(modelsData?.data) ? modelsData.data : []
    return raw
      .map((m) => (typeof m?.id === 'string' ? m.id : ''))
      .filter((mid) => mid && !hiddenNames.has(mid))
      .sort((a, b) => a.localeCompare(b))
  }, [modelsData, hiddenNames])

  useEffect(() => {
    if (!workspace) return
    setNameEdit(workspace.name || '')
    setDetailName(workspace.name || '')
    setDetailDesc(workspace.description || '')
    setDetailColor(workspace.color || '#7c3aed')
    setInferModel((workspace.model && String(workspace.model).trim()) || '')
    const rm = workspace.rag_mode
    setRagMode(rm === 'always' || rm === 'off' || rm === 'auto' ? rm : 'auto')
    setPinnedFlag(Boolean(workspace.pinned))
  }, [workspace])

  useEffect(() => {
    const hash = (typeof window !== 'undefined' && window.location.hash) || ''
    if (!hash) return
    // tiny delay so the section is mounted before the scroll
    const handle = window.setTimeout(() => {
      const el = document.getElementById(hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 50)
    return () => window.clearTimeout(handle)
  }, [id])

  const { data: files = [] } = useQuery({
    queryKey: ['workspace-context-files', id],
    queryFn: () => listContextFiles(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })
  const fileRows = Array.isArray(files) ? files : []

  const { data: instrPack } = useQuery({
    queryKey: ['workspaces', id, 'instructions'],
    queryFn: () => getWorkspaceInstructions(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  useEffect(() => {
    if (instrPack && typeof instrPack.content === 'string') setInstrDraft(instrPack.content)
  }, [instrPack])

  const { data: workspaceMemoryList = [], isError: memoryError } = useQuery({
    queryKey: ['workspaces', id, 'memory'],
    queryFn: () => getWorkspaceMemory(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })
  const memoryRows = Array.isArray(workspaceMemoryList) ? workspaceMemoryList : []

  const { data: workspaceSkillsList = [] } = useQuery({
    queryKey: ['workspaces', id, 'skills'],
    queryFn: () => getWorkspaceSkills(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  const { data: allSkills = [] } = useQuery({
    queryKey: ['skills'],
    queryFn: listSkills,
    staleTime: 30_000,
  })

  const attachSkillMutation = useMutation({
    mutationFn: ({ skillId, active }) => addSkillToWorkspace(id, skillId, active),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces', id, 'skills'] })
    },
  })

  const detachSkillMutation = useMutation({
    mutationFn: (skillId) => removeSkillFromWorkspace(id, skillId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces', id, 'skills'] })
    },
  })

  const toggleSkillMutation = useMutation({
    mutationFn: ({ skillId, active }) => toggleWorkspaceSkill(id, skillId, active),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces', id, 'skills'] })
    },
  })

  const attachedSkillIds = new Set(workspaceSkillsList.map((s) => s.id))
  const unattachedSkills = allSkills.filter((s) => !attachedSkillIds.has(s.id))

  function formatMemoryDate(iso) {
    if (!iso) return ''
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return ''
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  }

  const saveDetails = useMutation({
    mutationFn: () =>
      updateWorkspace(id, {
        name: detailName.trim() || 'Untitled',
        description: detailDesc.trim() || null,
        color: detailColor || '#7c3aed',
        pinned: pinnedFlag,
      }),
    onSuccess: () => invalidateWorkspace(),
  })

  const saveNameInline = useMutation({
    mutationFn: () => updateWorkspace(id, { name: nameEdit.trim() || 'Untitled' }),
    onSuccess: () => {
      setNameEditing(false)
      invalidateWorkspace()
    },
  })

  const uploadIconMut = useMutation({
    mutationFn: (file) => uploadWorkspaceIcon(id, file),
    onSuccess: () => invalidateWorkspace(),
  })

  const removeIconMut = useMutation({
    mutationFn: () => updateWorkspace(id, { icon_url: null }),
    onSuccess: () => invalidateWorkspace(),
  })

  const uploadFileMut = useMutation({
    mutationFn: (file) => uploadContextFile(id, file, false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-context-files', id] })
    },
  })

  const patchFileMut = useMutation({
    mutationFn: ({ fileId, embeddable }) => patchContextFile(fileId, { embeddable }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspace-context-files', id] }),
  })

  const delFileMut = useMutation({
    mutationFn: (fileId) => deleteContextFile(fileId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspace-context-files', id] }),
  })

  const saveInstr = useMutation({
    mutationFn: () => putWorkspaceInstructions(id, instrDraft),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces', id, 'instructions'] }),
  })

  const addMemoryMut = useMutation({
    mutationFn: () => addWorkspaceMemory(id, memoryDraft.trim()),
    onSuccess: () => {
      setMemoryDraft('')
      queryClient.invalidateQueries({ queryKey: ['workspaces', id, 'memory'] })
    },
  })

  const delMemoryMut = useMutation({
    mutationFn: (entryId) => deleteWorkspaceMemory(id, entryId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces', id, 'memory'] }),
  })

  const pinMut = useMutation({
    mutationFn: ({ pinned }) => pinWorkspace(id, pinned),
    onSuccess: () => invalidateWorkspace(),
  })

  const saveInferMut = useMutation({
    mutationFn: () => {
      const payload = {
        model: inferModel.trim() || null,
        rag_mode: ragMode,
      }
      return updateWorkspace(id, payload)
    },
    onSuccess: () => invalidateWorkspace(),
  })

  const clearEmbeddingsMut = useMutation({
    mutationFn: () => clearWorkspaceEmbeddings(id),
    onSuccess: () => {
      invalidateWorkspace()
      setShowClearConfirm(false)
      setClearing(false)
    },
  })

  if (!id) {
    return (
      <div className="p-4 text-sm text-muted-foreground">
        Missing workspace id. <Link to="/workspaces">Back</Link>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <div className="border-b border-border px-4 py-4">
        <Link to="/workspaces" className="text-sm text-muted-foreground hover:text-foreground">
          ← Workspaces
        </Link>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className="size-3 shrink-0 rounded-full"
            style={{ background: workspace?.color || '#7c3aed' }}
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
                    setNameEdit(workspace?.name || '')
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
                  setNameEdit(workspace?.name || '')
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
                setNameEdit(workspace?.name || '')
                setNameEditing(true)
              }}
            >
              {isLoading ? '…' : workspace?.name || 'Workspace'}
            </button>
          )}
        </div>
      </div>

      <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 p-4">
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {isError && <p className="text-sm text-destructive">Workspace not found.</p>}

        {workspace && (
          <>
            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Details</h2>
              <div className="flex flex-col gap-4">
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
                  <span className="text-sm text-foreground">Pin to sidebar</span>
                  <EmbeddableSwitch embeddable={pinnedFlag} disabled={false} onToggle={setPinnedFlag} />
                </div>
                <Button type="button" size="sm" onClick={() => saveDetails.mutate()} disabled={saveDetails.isPending}>
                  Save
                </Button>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Model and generation</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Optional pinned model for this workspace. Leave as &quot;Global default&quot; to use the model picker.
              </p>
              <div className="flex flex-col gap-4 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-muted-foreground">Model</span>
                  <select
                    value={inferModel}
                    onChange={(e) => setInferModel(e.target.value)}
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                  >
                    <option value="">Global default (model picker)</option>
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
                    value={ragMode}
                    onChange={(e) => setRagMode(e.target.value)}
                    disabled={saveInferMut.isPending}
                    className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <option value="auto">Auto (intent gate)</option>
                    <option value="always">Always</option>
                    <option value="off">Off</option>
                  </select>
                </label>
                <Button type="button" size="sm" onClick={() => saveInferMut.mutate()} disabled={saveInferMut.isPending}>
                  Save inference settings
                </Button>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Icon</h2>
              <div className="flex flex-col gap-3">
                {workspace.icon_url ? (
                  <img src={workspace.icon_url} alt={`${workspace.name || 'Workspace'} icon`} className="size-16 rounded-full object-cover" />
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
                  {workspace.icon_url ? (
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
              <h2 className="mb-3 text-sm font-medium text-foreground">Workspace Memory</h2>
              <p className="mb-3 text-xs text-muted-foreground">
                Entries are injected into every conversation in this workspace.
              </p>
              {memoryError ? (
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
                  <span>{memoryDraft.length} / 2000</span>
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
                AI skills attached to this workspace are injected into every conversation.
              </p>
              {workspaceSkillsList.length === 0 ? (
                <p className="mb-3 text-sm text-muted-foreground">No skills attached yet.</p>
              ) : (
                <ul className="mb-4 flex flex-col gap-2">
                  {workspaceSkillsList.map((skill) => (
                    <li
                      key={skill.id}
                      className="flex items-start justify-between gap-3 rounded-md border border-border/60 px-3 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-sm text-foreground">{skill.name}</span>
                          {skill.active && (
                            <span className="h-5 rounded bg-primary px-1.5 text-[10px] font-semibold uppercase text-primary-foreground">
                              Active
                            </span>
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

              <Dialog open={skillsAddDialogOpen} onOpenChange={setSkillsAddDialogOpen}>
                <DialogContent>
                  <DialogHeader>
                    <DialogTitle>Add Skill to Workspace</DialogTitle>
                    <DialogDescription>
                      Choose a skill from your library to attach to this workspace.
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
              <h2 className="mb-3 text-sm font-medium text-foreground">Pin settings</h2>
              <ul className="flex flex-col gap-3">
                <li className="flex items-center justify-between gap-3">
                  <span className="text-sm text-foreground">Pin in sidebar</span>
                  <EmbeddableSwitch
                    embeddable={workspace.pinned === true}
                    disabled={pinMut.isPending}
                    onToggle={(next) => pinMut.mutate({ pinned: next })}
                  />
                </li>
              </ul>
            </section>

            <section className="rounded-lg border border-destructive bg-destructive/5 p-4">
              <h2 className="mb-3 text-sm font-medium text-destructive">Danger zone</h2>
              <p className="mb-4 text-xs text-muted-foreground">
                Irreversible actions that affect this workspace&apos;s embeddings and sources.
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
              This will delete all chunks and embeddings for this workspace. Sources will need to be re-synced. Continue?
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
