import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { Pin } from 'lucide-react'

import { createDaw, deleteDaw, listDaws, pinDaw } from '@/api/daws.js'
import { Button } from '@/components/ui/button'
import { PATH_808NOTES, PATH_BOOOPS, is808notesRouteContext } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

function hexWithAlpha(color, alphaHex) {
  const raw = (color || '#7c3aed').replace(/^#/, '')
  const six = raw.length >= 6 ? raw.slice(0, 6) : '7c3aed'
  return `#${six}${alphaHex}`
}

function DawIcon({ daw }) {
  const color = daw.color || '#7c3aed'
  const letter = (daw.name || '?').trim().slice(0, 1).toUpperCase() || '?'
  if (daw.icon_url) {
    return (
      <img
        src={daw.icon_url}
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

export default function DawsPage() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const storeMode = useAppStore((s) => s.mode)
  const is808notes = is808notesRouteContext(pathname, storeMode)
  const routeBase = is808notes ? PATH_808NOTES : PATH_BOOOPS
  const listMode = is808notes ? '808notes' : 'booops'
  const pinSlot = is808notes ? '808notes' : 'booops'
  const queryClient = useQueryClient()
  const [showNew, setShowNew] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newColor, setNewColor] = useState('#7c3aed')
  const [deleteId, setDeleteId] = useState(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['daws', 'list', listMode],
    queryFn: () => listDaws(listMode),
    staleTime: 30_000,
  })
  const items = Array.isArray(data?.items) ? data.items : []

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['daws'] })
  }

  const createMut = useMutation({
    mutationFn: () =>
      createDaw({
        name: newName.trim() || 'Untitled',
        description: newDesc.trim() || null,
        color: newColor || '#7c3aed',
        mode: listMode,
      }),
    onSuccess: () => {
      invalidate()
      setShowNew(false)
      setNewName('')
      setNewDesc('')
      setNewColor('#7c3aed')
    },
  })

  const pinMut = useMutation({
    mutationFn: ({ id, pinned }) => pinDaw(id, pinSlot, pinned),
    onSuccess: () => invalidate(),
  })

  const delMut = useMutation({
    mutationFn: (id) => deleteDaw(id),
    onSuccess: () => {
      setDeleteId(null)
      invalidate()
    },
  })

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-auto bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-4">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-foreground">DAWs</h1>
          {is808notes ? (
            <p className="mt-0.5 text-sm text-muted-foreground">Create & manage DAWs for 808notes.</p>
          ) : null}
        </div>
        <Button type="button" size="sm" onClick={() => setShowNew((s) => !s)}>
          New DAW
        </Button>
      </header>

      <div className="flex-1 p-4">
        {showNew && (
          <div className="mb-4 rounded-lg border border-border bg-card p-4">
            <p className="mb-3 text-sm font-medium text-foreground">New DAW</p>
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

        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {isError && <p className="text-sm text-destructive">Could not load DAWs.</p>}
        {!isLoading && !isError && items.length === 0 && !showNew && (
          <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
            <p className="text-sm text-muted-foreground">No DAWs yet</p>
            <Button type="button" size="sm" onClick={() => setShowNew(true)}>
              New DAW
            </Button>
          </div>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((d) => {
            const bg = hexWithAlpha(d.color, '1a')
            const borderC = hexWithAlpha(d.color, '66')
            const pinned = pinSlot === '808notes' ? d.pinned_808notes === true : d.pinned_booops === true
            return (
              <div
                key={d.id}
                className="flex flex-col rounded-lg border p-4"
                style={{ backgroundColor: bg, borderColor: borderC }}
              >
                <div className="flex flex-col items-center gap-2">
                  <DawIcon daw={d} />
                  <p className="w-full text-center font-medium text-foreground">{d.name}</p>
                  <p className="line-clamp-2 w-full text-center text-sm text-muted-foreground">
                    {d.description || '—'}
                  </p>
                </div>
                <hr className="my-3 border-border/60" />
                {deleteId === d.id ? (
                  <div className="flex flex-col gap-2 text-sm">
                    <p className="text-muted-foreground">Delete this DAW?</p>
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
                      title={
                        pinned
                          ? `Unpin from ${is808notes ? '808notes' : 'BooOps'} sidebar`
                          : `Pin to ${is808notes ? '808notes' : 'BooOps'} sidebar`
                      }
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
                      <span className="sr-only">Pin {is808notes ? '808notes' : 'BooOps'}</span>
                    </button>
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={() => navigate(`${routeBase}/daws/${d.id}`)}
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
