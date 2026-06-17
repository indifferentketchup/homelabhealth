import { useEffect, useRef, useState } from 'react'
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
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { cn } from '@/lib/utils'

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
  // #8FAE92 = dark-mode accent; intentional hex for <input type="color"> initial value (CSS vars not accepted)
  const [detailColor, setDetailColor] = useState('#8FAE92')
  const [inferProviderId, setInferProviderId] = useState('')
  const [inferModel, setInferModel] = useState('')
  const [inferSaveErr, setInferSaveErr] = useState(null)
  const [inferSaveMsg, setInferSaveMsg] = useState(null)
  const [ragMode, setRagMode] = useState('auto')
  const [instrDraft, setInstrDraft] = useState('')
  const [memoryDraft, setMemoryDraft] = useState('')
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [pendingFileDelete, setPendingFileDelete] = useState(null)
  const [pendingMemoryDelete, setPendingMemoryDelete] = useState(null)
  const invalidateWorkspace = () => {
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const { data: workspace, isLoading, isError } = useQuery({
    queryKey: ['workspaces', id],
    queryFn: () => getWorkspace(id),
    enabled: Boolean(id),
    staleTime: 15_000,
  })

  useEffect(() => {
    if (!workspace) return
    setNameEdit(workspace.name || '')
    setDetailName(workspace.name || '')
    setDetailDesc(workspace.description || '')
    setDetailColor(workspace.color || '#8FAE92') // hex required for <input type="color">
    setInferProviderId(workspace.provider_id || '')
    setInferModel((workspace.model && String(workspace.model).trim()) || '')
    const rm = workspace.rag_mode
    setRagMode(rm === 'always' || rm === 'off' || rm === 'auto' ? rm : 'auto')
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
        color: detailColor || '#8FAE92', // DB stores hex; color picker always yields a valid hex once touched
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
      // Spec: provider_id + model are paired (CHECK constraint). Send both
      // together as either (uuid, string) or (null, null). The backend
      // returns 400 if the pair is mismatched; surface that inline.
      const pid = inferProviderId.trim() || null
      const mdl = inferModel.trim() || null
      const payload = {
        provider_id: pid,
        model: mdl,
        rag_mode: ragMode,
      }
      return updateWorkspace(id, payload)
    },
    onSuccess: () => {
      setInferSaveErr(null)
      setInferSaveMsg(
        inferProviderId && inferModel
          ? 'Inference settings saved.'
          : 'Provider + model cleared. Chat send will surface the "no provider configured" message until you re-bind.',
      )
      invalidateWorkspace()
    },
    onError: (e) => {
      const raw = e instanceof Error ? e.message : 'Save failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch {
        /* not JSON */
      }
      setInferSaveErr(pretty)
      setInferSaveMsg(null)
    },
  })

  useEffect(() => {
    if (!inferSaveMsg) return
    const t = window.setTimeout(() => setInferSaveMsg(null), 5000)
    return () => window.clearTimeout(t)
  }, [inferSaveMsg])

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
            style={{ background: workspace?.color || 'var(--accent-workspace)' }}
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
                <Button type="button" size="sm" onClick={() => saveDetails.mutate()} disabled={saveDetails.isPending}>
                  Save
                </Button>
              </div>
            </section>

            <section className="rounded-lg border border-border bg-card p-4">
              <h2 className="mb-3 text-sm font-medium text-foreground">Provider, model, and generation</h2>

              {inferSaveErr ? (
                <p data-testid="workspace-infer-save-error" className="mb-3 text-sm text-destructive">
                  {inferSaveErr}
                </p>
              ) : null}
              {inferSaveMsg ? <p className="mb-3 text-sm text-foreground">{inferSaveMsg}</p> : null}

              {/* ── Chat provider (locked to bundled) + RAG mode ── */}
              <div className="rounded-lg border border-border bg-card p-3">
                <div className="text-sm font-medium text-foreground">Chat provider</div>
                <p className="mt-1 text-sm">
                  <span className="font-mono text-foreground">HomeLab Health AI</span>
                  {workspace.model ? (
                    <span className="text-muted-foreground">
                      {' · model '}
                      <span className="font-mono text-foreground">{workspace.model}</span>
                    </span>
                  ) : null}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Bundled by the homelabhealth stack. Change hardware tier in Settings → System to swap the chat model.
                </p>
              </div>

              <div className="mt-3 rounded-lg border border-border bg-card p-3">
                <label className="flex flex-col gap-1 text-sm">
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
                <div className="mt-3">
                  <Button
                    type="button"
                    size="sm"
                    onClick={() => saveInferMut.mutate()}
                    disabled={saveInferMut.isPending}
                  >
                    {saveInferMut.isPending ? 'Saving…' : 'Save'}
                  </Button>
                </div>
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
                          onClick={() => setPendingFileDelete(f.id)}
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
                        onClick={() => setPendingMemoryDelete(entry.id)}
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

      <ConfirmDialog
        open={showClearConfirm}
        onOpenChange={setShowClearConfirm}
        title="Clear Embeddings?"
        description="This will delete all chunks and embeddings for this workspace. Sources will need to be re-synced."
        confirmLabel="Clear Embeddings"
        onConfirm={() => {
          setShowClearConfirm(false)
          setClearing(true)
          clearEmbeddingsMut.mutate()
        }}
      />

      <ConfirmDialog
        open={Boolean(pendingFileDelete)}
        onOpenChange={(open) => { if (!open) setPendingFileDelete(null) }}
        title="Delete this context file?"
        description="This file will be permanently removed from the workspace."
        confirmLabel="Delete"
        onConfirm={() => {
          delFileMut.mutate(pendingFileDelete)
          setPendingFileDelete(null)
        }}
      />

      <ConfirmDialog
        open={Boolean(pendingMemoryDelete)}
        onOpenChange={(open) => { if (!open) setPendingMemoryDelete(null) }}
        title="Delete this memory entry?"
        description="This entry will be permanently removed."
        confirmLabel="Delete"
        onConfirm={() => {
          delMemoryMut.mutate(pendingMemoryDelete)
          setPendingMemoryDelete(null)
        }}
      />
    </div>
  )
}
