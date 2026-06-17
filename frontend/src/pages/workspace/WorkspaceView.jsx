import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom'
import { Layers, Pin, Stethoscope, Loader2 } from 'lucide-react'
import * as LucideIcons from 'lucide-react'

import { createWorkspace, deleteWorkspace, listWorkspaces, loadDemo, pinWorkspace } from '@/api/workspaces.js'
import { deleteSource, listSources, uploadSource } from '@/api/sources.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import ModelStateSidebar from '@/components/chat/ModelStateSidebar.jsx'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { APP_GLYPH, APP_TAGLINE, APP_TITLE } from '@/config/identity.js'
import { workspacePath } from '@/routes/paths.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

import { NotesPanel } from './NotesPanel.jsx'
import { SourcesPanel } from './SourcesPanel.jsx'

const { ChevronDown, ChevronLeft, ChevronRight, PanelRight } = LucideIcons

function LandingLucide({ name, className, style }) {
  const C =
    LucideIcons[name] && typeof LucideIcons[name] === 'function'
      ? LucideIcons[name]
      : LucideIcons.Stethoscope
  return <C className={className} style={style} aria-hidden />
}

function firstDisplayChar(name) {
  const s = (name || '?').trim() || '?'
  const arr = [...s]
  return arr[0] || '?'
}

function WorkspaceLandingIcon({ workspace }) {
  if (workspace.icon_url) {
    return <img src={workspace.icon_url} alt="" loading="lazy" className="workspace-landing-card__icon-img" />
  }
  const ch = firstDisplayChar(workspace.name)
  return (
    <div
      className="workspace-landing-card__icon-fallback"
      style={workspace?.color ? { '--workspace-tint': workspace.color } : undefined}
      aria-hidden
    >
      {ch}
    </div>
  )
}

function readAccentCss() {
  try {
    const el = document.querySelector('.layout') ?? document.documentElement
    const v = getComputedStyle(el).getPropertyValue('--accent').trim()
    return v || null
  } catch {
    return null
  }
}

export function WorkspaceLanding() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const layoutRef = useRef(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newEmoji, setNewEmoji] = useState('🎛️')
  const [deleteId, setDeleteId] = useState(null)
  const [demoErr, setDemoErr] = useState(null)

  const currentUser = useAppStore((s) => s.currentUser)
  const isAdmin = currentUser?.role === 'owner' || currentUser?.role === 'super_admin'

  const { data, isLoading, isError } = useQuery({
    queryKey: ['workspaces', 'landing'],
    queryFn: () => listWorkspaces(),
    staleTime: 30_000,
  })
  const items = Array.isArray(data?.items) ? data.items : []

  const createMut = useMutation({
    mutationFn: async () => {
      const accent = readAccentCss()
      const baseName = newName.trim() || 'Untitled Workspace'
      const name =
        newEmoji.trim() && !baseName.startsWith(newEmoji.trim())
          ? `${newEmoji.trim()} ${baseName}`
          : baseName
      return createWorkspace({
        name,
        description: newDesc.trim() || null,
        ...(accent ? { color: accent } : {}),
      })
    },
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setModalOpen(false)
      setNewName('')
      setNewDesc('')
      setNewEmoji('🎛️')
      const id = row?.id
      if (id) navigate(workspacePath(id))
    },
  })

  const pinMut = useMutation({
    mutationFn: ({ id, pinned }) => pinWorkspace(id, pinned),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['workspaces'] }),
  })

  const delMut = useMutation({
    mutationFn: (id) => deleteWorkspace(id),
    onSuccess: () => {
      setDeleteId(null)
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
    },
  })

  const demoMut = useMutation({
    mutationFn: () => loadDemo(),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      if (data?.workspace_id) {
        navigate(workspacePath(data.workspace_id))
      }
    },
    onError: (e) => {
      setDemoErr(e instanceof Error ? e.message : 'Failed to load demo')
    },
  })

  return (
    <div ref={layoutRef} className="workspace-landing flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="workspace-landing__shell">
        <header className="workspace-landing__hero">
          <div className="workspace-landing__hero-row">
            <div className="workspace-landing__logo-box">
              <div className="workspace-landing__logo-glyph">
                <LandingLucide
                  name={APP_GLYPH}
                  className="workspace-landing__logo-icon"
                  style={{
                    color: 'var(--accent)',
                    filter: 'drop-shadow(0 0 10px color-mix(in srgb, var(--accent) 50%, transparent))',
                  }}
                />
              </div>
            </div>
            <div className="workspace-landing__hero-text min-w-0 flex-1">
              <h1 className="workspace-landing__hub-title">{APP_TITLE}</h1>
              {APP_TAGLINE ? <p className="workspace-landing__hub-tagline">{APP_TAGLINE}</p> : null}
            </div>
          </div>
          <p className="workspace-landing__intro text-muted-foreground">
            Pick a workspace to open its chat and sources, or create a new workspace.
          </p>
          <Button type="button" className="workspace-landing__cta mt-4" onClick={() => setModalOpen(true)}>
            New Workspace
          </Button>
        </header>

        <section className="workspace-landing__section">
          <div className="workspace-landing__section-rule">
            <span className="workspace-landing__section-rule-accent" />
            <span className="workspace-landing__section-rule-label">workspaces</span>
            <span className="workspace-landing__section-rule-line" />
          </div>
          {isLoading && <p className="text-sm text-muted-foreground">Loading workspaces…</p>}
          {isError && <p className="text-sm text-destructive">Could not load workspaces.</p>}
          {!isLoading && !isError && items.length === 0 && (
            <div className="flex flex-col items-center gap-4 py-12 text-center">
              <div className="flex size-12 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground">
                <Layers className="size-6" aria-hidden />
              </div>
              <p className="text-sm text-muted-foreground">No workspaces yet  -  create one to get started.</p>
              {isAdmin && (
                <div className="flex flex-col items-center gap-3 rounded-lg border border-border bg-card p-6">
                  <div className="flex size-10 items-center justify-center rounded-full bg-accent/10 text-accent">
                    <Stethoscope className="size-5" aria-hidden />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-foreground">Try a demo</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">Load sample health records to see HomeLab Health in action.</p>
                  </div>
                  {demoErr && (
                    <p className="text-xs text-destructive">{demoErr}</p>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={demoMut.isPending}
                    onClick={() => { setDemoErr(null); demoMut.mutate() }}
                  >
                    {demoMut.isPending ? (
                      <span className="flex items-center gap-2">
                        <Loader2 className="size-3.5 animate-spin" />
                        Loading demo data…
                      </span>
                    ) : (
                      'Try Demo'
                    )}
                  </Button>
                </div>
              )}
            </div>
          )}
          {!isLoading && !isError && items.length > 0 && isAdmin && (
            <div className="mt-4 flex items-center justify-center">
              <button
                type="button"
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-accent transition-colors"
                disabled={demoMut.isPending}
                onClick={() => { setDemoErr(null); demoMut.mutate() }}
              >
                {demoMut.isPending ? (
                  <Loader2 className="size-3 animate-spin" />
                ) : (
                  <Stethoscope className="size-3" />
                )}
                {demoMut.isPending ? 'Loading demo…' : 'New here? Try a demo workspace →'}
              </button>
              {demoErr && (
                <p className="ml-3 text-xs text-destructive">{demoErr}</p>
              )}
            </div>
          )}
          <div className="workspace-landing__cards">
            {items.map((d) => {
              const pinned = d.pinned === true
              return (
                <div
                  key={d.id}
                  className={cn(
                    'workspace-landing-card group text-card-foreground',
                    'transition-colors hover:border-accent',
                    'relative',
                  )}
                  style={
                    d?.color
                      ? { '--workspace-card-tint': d.color }
                      : undefined
                  }
                >
                  <div className="workspace-landing-card__ribbon" aria-hidden />
                  <Link
                    to={workspacePath(d.id)}
                    className="workspace-landing-card__body"
                  >
                    <WorkspaceLandingIcon workspace={d} />
                    <h2 className="workspace-landing-card__name">{d.name || 'Untitled'}</h2>
                    {d.description ? (
                      <p className="workspace-landing-card__desc">{d.description}</p>
                    ) : (
                      <p className="workspace-landing-card__desc workspace-landing-card__desc--placeholder">
                        No description
                      </p>
                    )}
                  </Link>
                  {deleteId === d.id ? (
                    <div className="flex items-center justify-between gap-3 px-4 py-3">
                      <p className="text-sm text-muted-foreground">Delete this workspace?</p>
                      <div className="flex gap-2">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-11 px-3 text-xs"
                          onClick={() => setDeleteId(null)}
                        >
                          Cancel
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          className="h-11 px-3 text-xs"
                          onClick={() => delMut.mutate(d.id)}
                          disabled={delMut.isPending}
                        >
                          Delete
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-2 px-4 py-3">
                      <div className="flex items-center">
                        <button
                          type="button"
                          title={pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
                          onClick={() => pinMut.mutate({ id: d.id, pinned: !pinned })}
                          disabled={pinMut.isPending}
                          className="flex items-center gap-1 rounded-md p-1.5 text-muted-foreground hover:bg-background/50 hover:text-foreground disabled:opacity-50"
                        >
                          <Pin
                            className={cn(
                              'size-5 text-foreground',
                              pinned ? 'fill-current' : 'fill-none stroke-2',
                            )}
                            aria-hidden
                          />
                          <span className="sr-only">Pin workspace</span>
                        </button>
                        <div className="flex gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="secondary"
                            className="h-11 px-3 text-xs"
                            onClick={() => navigate(`/workspaces/${d.id}`)}
                          >
                            Edit
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="destructive"
                            className="h-11 px-3 text-xs"
                            onClick={() => setDeleteId(d.id)}
                          >
                            Delete
                          </Button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </section>
      </div>

      {modalOpen && (
        <div className="workspace-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="workspace-new-title">
          <button type="button" className="workspace-modal-backdrop" aria-label="Close" onClick={() => setModalOpen(false)} />
          <div className="workspace-modal border border-border bg-card p-6 shadow-lg">
            <h2 id="workspace-new-title" className="text-lg font-semibold text-foreground">
              New Workspace
            </h2>
            <div className="mt-4 flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Name</span>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="rounded-md border border-border bg-background px-3 py-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Description</span>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  rows={3}
                  className="resize-y rounded-md border border-border bg-background px-3 py-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Icon emoji</span>
                <input
                  value={newEmoji}
                  onChange={(e) => setNewEmoji(e.target.value.slice(0, 8))}
                  className="max-w-[6rem] rounded-md border border-border bg-background px-3 py-2 text-2xl leading-none text-foreground outline-none ring-ring focus-visible:ring-2"
                  placeholder="🎹"
                />
              </label>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setModalOpen(false)}>
                Cancel
              </Button>
              <Button type="button" disabled={createMut.isPending} onClick={() => createMut.mutate()}>
                {createMut.isPending ? 'Creating…' : 'Create'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function WorkspaceLayout() {
  const { workspaceId } = useParams()
  const setActiveWorkspaceId = useAppStore((s) => s.setActiveWorkspaceId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const prevWorkspaceIdRef = useRef(workspaceId ?? null)

  useEffect(() => {
    if (!workspaceId) return
    setActiveWorkspaceId(workspaceId)
    if (prevWorkspaceIdRef.current && prevWorkspaceIdRef.current !== workspaceId) {
      setActiveChatId(null)
    }
    prevWorkspaceIdRef.current = workspaceId
  }, [workspaceId, setActiveWorkspaceId, setActiveChatId])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <Outlet />
    </div>
  )
}

export function WorkspaceChat() {
  const { workspaceId } = useParams()
  const activeChatId = useAppStore((s) => s.activeChatId)
  const [filesPanelExpanded, setFilesPanelExpanded] = useState(true)
  const filesRailCollapsed = !filesPanelExpanded
  const [notesOpen, setNotesOpen] = useState(false)
  // Model-load tracker is always visible  -  no toggle. (Previously hidden behind
  // a per-browser localStorage flag, which made it inconsistent across devices.)
  const [rightPanelWidth, setRightPanelWidth] = useState(320)
  const resizingRef = useRef(false)

  useEffect(() => {
    function onMouseMove(e) {
      if (!resizingRef.current) return
      const newWidth = window.innerWidth - e.clientX
      setRightPanelWidth(Math.max(200, Math.min(600, newWidth)))
    }
    function onMouseUp() {
      resizingRef.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="flex min-h-0 min-w-0 flex-1">
        <ChatView workspaceId={workspaceId} />
      </div>
      {!filesRailCollapsed && (
        <div
          className="hidden h-full cursor-col-resize bg-transparent hover:bg-primary/20 active:bg-primary/40 transition-colors md:block w-1 shrink-0 z-[51]"
          onMouseDown={(e) => {
            e.preventDefault()
            resizingRef.current = true
            document.body.style.cursor = 'col-resize'
            document.body.style.userSelect = 'none'
          }}
        />
      )}
      <div
        className={cn(
          'hidden h-full min-h-0 shrink-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground md:flex z-[50]',
          filesRailCollapsed && 'w-14',
        )}
        style={!filesRailCollapsed ? { width: rightPanelWidth } : undefined}
      >
        <div className="flex shrink-0 items-center justify-end gap-2 border-b border-sidebar-border p-2">
          <Button
            type="button"
            variant="outline"
            size="icon"
            className="h-9 w-9 shrink-0 border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent"
            onClick={() => setFilesPanelExpanded((v) => !v)}
            aria-label={filesRailCollapsed ? 'Expand workspace panel' : 'Collapse workspace panel'}
          >
            {filesRailCollapsed ? <PanelRight className="size-4" /> : <ChevronRight className="size-4" />}
          </Button>
        </div>
        {!filesRailCollapsed ? (
          <>
            <div className="shrink-0 border-b border-sidebar-border p-2">
              <ModelStateSidebar />
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <SourcesPanel chatId={activeChatId} workspaceId={workspaceId} />
            </div>
            <div className={cn("flex flex-col overflow-hidden border-t border-sidebar-border", notesOpen ? "min-h-0 flex-[2]" : "shrink-0")}>
              <button
                type="button"
                onClick={() => setNotesOpen(o => !o)}
                className="flex w-full items-center justify-between px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-sidebar-accent/30"
              >
                <span>Notes</span>
                <ChevronDown className={cn("size-3 transition-transform", !notesOpen && "-rotate-90")} />
              </button>
              {notesOpen && <NotesPanel workspaceId={workspaceId} />}
            </div>
          </>
        ) : null}
      </div>
    </div>
  )
}

export function WorkspaceSourcesPage() {
  const { workspaceId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const fileRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [status, setStatus] = useState('')
  const [pendingDelete, setPendingDelete] = useState(null)

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['sources', workspaceId],
    queryFn: () => listSources(workspaceId),
    enabled: Boolean(workspaceId),
    refetchInterval: (q) => {
      const rows = q.state.data
      if (!Array.isArray(rows)) return false
      return rows.some((r) => r.embedding_status === 'processing' || r.embedding_status === 'pending')
        ? 2000
        : false
    },
  })

  function sendToChat(src) {
    window.dispatchEvent(new CustomEvent('hlh:attach-source', {
      detail: { name: src.name || src.filename, id: src.id },
    }))
    navigate(workspacePath(workspaceId))
  }

  async function onUpload(e) {
    const files = Array.from(e.target.files || [])
    e.target.value = ''
    if (!files.length || !workspaceId) return
    setUploading(true)
    setStatus('')
    try {
      if (files.length === 1) {
        const res = await uploadSource(files[0], workspaceId)
        if (res?.status === 'already_exists') setStatus('Already ingested (same file hash).')
        else setStatus(`Ingesting ${files[0].name}…`)
      } else {
        const { uploadSources } = await import('@/api/sources.js')
        const res = await uploadSources(files, workspaceId)
        const count = res?.sources?.length || files.length
        setStatus(`Ingesting ${count} file${count > 1 ? 's' : ''}…`)
      }
      await queryClient.invalidateQueries({ queryKey: ['sources', workspaceId] })
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function executeSourceDelete() {
    if (!pendingDelete) return
    const { id } = pendingDelete
    setPendingDelete(null)
    try {
      await deleteSource(id)
      await queryClient.invalidateQueries({ queryKey: ['sources', workspaceId] })
    } catch {
      setStatus('Delete failed')
    }
  }

  const backPath = workspacePath(workspaceId)

  return (
    <div className="workspace-sources-page flex min-h-0 flex-1 flex-col overflow-auto bg-background px-4 py-6">
      <div className="mx-auto w-full max-w-2xl">
        <Button type="button" variant="ghost" size="sm" className="mb-4 gap-1 px-0" asChild>
          <Link to={backPath}>
            <ChevronLeft className="size-4" />
            Back to chat
          </Link>
        </Button>
        <h1 className="text-lg font-semibold text-foreground">Sources</h1>
        <p className="mt-1 text-sm text-muted-foreground">Documents embedded for this workspace.</p>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".txt,.md,.pdf,.docx,.png,.jpg,.jpeg,.tiff,.bmp,text/plain,text/markdown,application/pdf,image/*"
            className="sr-only"
            disabled={uploading || !workspaceId}
            onChange={(ev) => void onUpload(ev)}
          />
          <Button
            type="button"
            disabled={uploading || !workspaceId}
            onClick={() => fileRef.current?.click()}
          >
            Upload
          </Button>
          {status ? <span className="text-sm text-muted-foreground">{status}</span> : null}
        </div>

        <ul className="mt-6 flex flex-col gap-2">
          {isLoading && <li className="text-sm text-muted-foreground">Loading…</li>}
          {!isLoading && sources.length === 0 && (
            <li className="text-sm text-muted-foreground">No sources yet.</li>
          )}
          {sources.map((s) => {
            const ready = s.embedding_status === 'complete'
            return (
              <li
                key={s.id}
                className="flex flex-col gap-2 rounded-lg border border-border bg-card px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">{s.name || s.filename || 'Source'}</p>
                  {s.embedding_status ? (
                    <p className="text-xs text-muted-foreground">{s.embedding_status}</p>
                  ) : null}
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="min-w-[7.5rem] flex-1 sm:flex-none"
                    disabled={!ready}
                    onClick={() => sendToChat(s)}
                  >
                    Send to Chat
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="shrink-0 text-destructive hover:bg-destructive/10"
                    onClick={() => setPendingDelete({ id: s.id, name: s.name || s.filename })}
                  >
                    Delete
                  </Button>
                </div>
              </li>
            )
          })}
        </ul>
      </div>
      <ConfirmDialog
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => { if (!open) setPendingDelete(null) }}
        title={`Delete "${pendingDelete?.name}"?`}
        description="This source will be permanently removed."
        confirmLabel="Delete"
        onConfirm={() => void executeSourceDelete()}
      />
    </div>
  )
}

export function WorkspaceAuxShell() {
  const activeChatId = useAppStore((s) => s.activeChatId)
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId)
  const sidebarW = useLayoutStore((s) => s.sidebarWidth) || 260

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden bg-background md:flex-row">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
      <div
        className="hidden h-full min-h-0 shrink-0 md:flex"
        style={{ width: sidebarW }}
      >
        <SourcesPanel chatId={activeChatId} workspaceId={activeWorkspaceId} />
      </div>
    </div>
  )
}
