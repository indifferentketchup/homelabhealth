import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Loader2, Pin, Layers } from 'lucide-react'

import { createWorkspace, deleteWorkspace, listWorkspaces, pinWorkspace } from '@/api/workspaces.js'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

function hexWithAlpha(color, alphaHex) {
  // Fallback '#8FAE92' must stay as hex: this function does string slicing to build '#rrggbbAA'.
  // CSS vars cannot be used here. '8FAE92' is the dark-mode accent (--accent-workspace).
  const raw = (color || '#8FAE92').replace(/^#/, '')
  const six = raw.length >= 6 ? raw.slice(0, 6) : '8FAE92'
  return `#${six}${alphaHex}`
}

function WorkspaceIcon({ workspace }) {
  // Use CSS var as fallback so the icon follows the theme when no color is set in the DB
  const color = workspace.color || 'var(--accent-workspace)'
  const letter = (workspace.name || '?').trim().slice(0, 1).toUpperCase() || '?'
  if (workspace.icon_url) {
    return (
      <img
        src={workspace.icon_url}
        alt=""
        className="size-12 shrink-0 rounded-full object-cover"
      />
    )
  }
  return (
    <div
      className="flex size-12 shrink-0 items-center justify-center rounded-full text-lg font-semibold text-white"
      style={{ backgroundColor: color }}
      aria-hidden
    >
      {letter}
    </div>
  )
}

export default function WorkspacesPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  // #8FAE92 = dark-mode accent; intentional hex for <input type="color"> initial value
  const [newColor, setNewColor] = useState('#8FAE92')
  const [deleteId, setDeleteId] = useState(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => listWorkspaces(),
    staleTime: 30_000,
  })
  const items = Array.isArray(data?.items) ? data.items : []

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const createMut = useMutation({
    mutationFn: () =>
      createWorkspace({
        name: newName.trim() || 'Untitled',
        description: newDesc.trim() || null,
        color: newColor || '#8FAE92', // DB stores hex; color picker always yields a valid hex once touched
      }),
    onSuccess: () => {
      invalidate()
      setShowNew(false)
      setNewName('')
      setNewDesc('')
      setNewColor('#8FAE92') // reset color picker to default hex
    },
  })

  const pinMut = useMutation({
    mutationFn: ({ id, pinned }) => pinWorkspace(id, pinned),
    onSuccess: () => invalidate(),
  })

  const delMut = useMutation({
    mutationFn: (id) => deleteWorkspace(id),
    onSuccess: () => {
      setDeleteId(null)
      invalidate()
    },
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-4 md:pr-[4.75rem]">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">Workspaces</h1>
          <p className="mt-0.5 text-sm text-muted-foreground">Create and manage workspaces.</p>
        </div>
        <Button type="button" size="sm" onClick={() => setShowNew((s) => !s)}>
          New Workspace
        </Button>
      </header>

      <div className="flex-1 p-4">
        {showNew && (
          <div className="mb-4 rounded-lg border border-border bg-card p-4">
            <p className="mb-3 text-sm font-medium text-foreground">New Workspace</p>
            <div className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Name</span>
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Description</span>
                <textarea
                  value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  rows={3}
                  className="resize-y rounded-md border border-border bg-background px-2 py-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Color</span>
                <input
                  type="color"
                  value={newColor}
                  onChange={(e) => setNewColor(e.target.value)}
                  className="h-9 w-24 cursor-pointer rounded-md border border-border bg-background"
                />
              </label>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  onClick={() => createMut.mutate()}
                  disabled={createMut.isPending}
                >
                  Save
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={() => setShowNew(false)}>
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        )}

        {isLoading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading…
          </div>
        )}
        {isError && <p className="text-sm text-destructive">Could not load workspaces.</p>}
        {!isLoading && !isError && items.length === 0 && !showNew && (
          <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
            <div className="flex size-12 items-center justify-center rounded-full border border-border bg-muted text-muted-foreground">
              <Layers className="size-6" aria-hidden />
            </div>
            <div className="space-y-1">
              <p className="text-sm font-medium text-foreground">No workspaces yet</p>
              <p className="text-xs text-muted-foreground">Create one to organize chats, sources, and memory.</p>
            </div>
            <Button type="button" size="sm" onClick={() => setShowNew(true)}>
              New Workspace
            </Button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((d) => {
            const bg = hexWithAlpha(d.color, '1a')
            const borderC = hexWithAlpha(d.color, '66')
            const pinned = d.pinned === true
            return (
              <div
                key={d.id}
                className="flex flex-col rounded-lg border p-4"
                style={{ backgroundColor: bg, borderColor: borderC }}
              >
                <div className="flex flex-col items-center gap-2">
                  <WorkspaceIcon workspace={d} />
                  <p className="w-full text-center font-medium text-foreground">{d.name}</p>
                  <p className="line-clamp-2 w-full text-center text-sm text-muted-foreground">
                    {d.description || '—'}
                  </p>
                </div>
                <hr className="my-3 border-border/60" />
                {deleteId === d.id ? (
                  <div className="flex flex-col gap-2 text-sm">
                    <p className="text-muted-foreground">Delete this workspace?</p>
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" size="sm" variant="outline" onClick={() => setDeleteId(null)}>
                        Cancel
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        onClick={() => delMut.mutate(d.id)}
                        disabled={delMut.isPending}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <button
                      type="button"
                      title={pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
                      onClick={() => pinMut.mutate({ id: d.id, pinned: !pinned })}
                      disabled={pinMut.isPending}
                      className="flex items-center gap-1 rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-background/50 hover:text-foreground disabled:opacity-50"
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
                        onClick={() => navigate(`/workspaces/${d.id}`)}
                      >
                        Edit
                      </Button>
                      <Button type="button" size="sm" variant="destructive" onClick={() => setDeleteId(d.id)}>
                        Delete
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
