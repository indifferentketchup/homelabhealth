import { useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Trash2 } from 'lucide-react'

import { createNote, deleteNote, listNotes, updateNote } from '@/api/notes.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils'

export function NotesPanel({ workspaceId }) {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState(null)
  const [listOpen, setListOpen] = useState(true)
  const [localTitle, setLocalTitle] = useState('')
  const [localContent, setLocalContent] = useState('')
  const skipDebounceRef = useRef(false)
  const debounceTimerRef = useRef(null)
  const lastSavedRef = useRef({ title: '', content: '' })

  const { data: notes = [], isLoading } = useQuery({
    queryKey: ['notes', workspaceId],
    queryFn: () => listNotes(workspaceId),
    enabled: Boolean(workspaceId),
  })

  useEffect(() => {
    if (!selectedId) {
      setLocalTitle('')
      setLocalContent('')
      lastSavedRef.current = { title: '', content: '' }
      return
    }
    const row = notes.find((n) => n.id === selectedId)
    if (!row) {
      setSelectedId(null)
      return
    }
    skipDebounceRef.current = true
    const t = row.title ?? ''
    const c = row.content ?? ''
    setLocalTitle(t)
    setLocalContent(c)
    lastSavedRef.current = { title: t, content: c }
  }, [selectedId, notes])

  const persist = useCallback(async () => {
    if (!selectedId || !workspaceId) return
    if (
      localTitle === lastSavedRef.current.title &&
      localContent === lastSavedRef.current.content
    ) {
      return
    }
    await updateNote(selectedId, { title: localTitle, content: localContent })
    lastSavedRef.current = { title: localTitle, content: localContent }
    await queryClient.invalidateQueries({ queryKey: ['notes', workspaceId] })
  }, [selectedId, workspaceId, localTitle, localContent, queryClient])

  useEffect(() => {
    if (!selectedId || !workspaceId) return
    if (skipDebounceRef.current) {
      skipDebounceRef.current = false
      return
    }
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null
      void persist()
    }, 800)
    return () => {
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current)
        debounceTimerRef.current = null
      }
    }
  }, [localTitle, localContent, selectedId, workspaceId, persist])

  function flushSave() {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    void persist()
  }

  const createMut = useMutation({
    mutationFn: () => createNote(workspaceId, { content: '', source_type: 'manual' }),
    onSuccess: async (row) => {
      await queryClient.invalidateQueries({ queryKey: ['notes', workspaceId] })
      if (row?.id) setSelectedId(row.id)
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id) => deleteNote(id),
    onSuccess: async (_, id) => {
      if (selectedId === id) {
        setSelectedId(null)
        setLocalTitle('')
        setLocalContent('')
        lastSavedRef.current = { title: '', content: '' }
      }
      await queryClient.invalidateQueries({ queryKey: ['notes', workspaceId] })
    },
  })

  return (
    <aside className="flex h-full min-h-0 w-full min-w-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground">
      <div className="border-b border-sidebar-border">
        <div className="flex w-full items-center justify-between gap-2 overflow-hidden px-2 py-1.5">
          <button
            type="button"
            onClick={() => setListOpen((o) => !o)}
            className="fs-nav flex items-center gap-1 font-semibold uppercase tracking-wide text-muted-foreground outline-none"
          >
            <ChevronDown
              className={cn('size-4 shrink-0 transition-transform duration-150', !listOpen && '-rotate-90')}
              aria-hidden
            />
            Notes
          </button>
          <Button
            type="button"
            className="fs-nav h-7 shrink-0 px-2"
            variant="secondary"
            size="sm"
            disabled={!workspaceId || createMut.isPending}
            onClick={() => createMut.mutate()}
          >
            + New
          </Button>
        </div>
      </div>

      <ScrollArea className={cn("min-h-0 flex-[3]", !listOpen && "hidden")}>
        <div className="flex flex-col gap-0.5 p-2 pb-2">
          {!workspaceId ? (
            <p className="fs-nav px-1 text-muted-foreground">Open a workspace to see notes.</p>
          ) : isLoading ? (
            <p className="fs-nav px-1 text-muted-foreground">Loading…</p>
          ) : notes.length === 0 ? (
            <p className="fs-nav px-1 text-muted-foreground">No notes yet.</p>
          ) : (
            notes.map((n) => {
              const active = n.id === selectedId
              const label = (n.title || '').trim() || (n.content || '').slice(0, 48) || 'Untitled'
              return (
                <div
                  key={n.id}
                  className={cn(
                    'group flex w-full items-stretch gap-0.5 rounded-md border border-transparent py-0.5',
                    active
                      ? 'border-sidebar-border bg-sidebar-accent/40'
                      : 'hover:border-sidebar-border hover:bg-sidebar-accent/30',
                  )}
                >
                  <button
                    type="button"
                    className="fs-nav min-w-0 flex-1 truncate px-2 py-1.5 text-left font-medium text-foreground outline-none ring-sidebar-ring focus-visible:ring-2"
                    onClick={() => setSelectedId(n.id)}
                  >
                    {label}
                  </button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive"
                    title="Delete note"
                    onClick={() => deleteMut.mutate(n.id)}
                  >
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              )
            })
          )}
        </div>
      </ScrollArea>

      <div className="flex min-h-0 flex-[2] flex-col gap-2 overflow-hidden border-t border-sidebar-border p-2">
        {!selectedId || !workspaceId ? (
          <p className="fs-nav text-muted-foreground">Select a note to edit.</p>
        ) : (
          <>
            <input
              type="text"
              className="fs-input h-9 w-full shrink-0 rounded-md border border-sidebar-border bg-card px-2 text-foreground outline-none ring-sidebar-ring focus-visible:ring-2"
              placeholder="Title"
              value={localTitle}
              onChange={(e) => setLocalTitle(e.target.value)}
              onBlur={() => flushSave()}
            />
            <textarea
              className="fs-nav min-h-0 flex-1 resize-none rounded-md border border-sidebar-border bg-card p-2 text-foreground outline-none ring-sidebar-ring focus-visible:ring-2"
              placeholder="Write…"
              value={localContent}
              onChange={(e) => setLocalContent(e.target.value)}
              onBlur={() => flushSave()}
            />
          </>
        )}
      </div>
    </aside>
  )
}
