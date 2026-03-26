import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowLeft, Trash2 } from 'lucide-react'

import { deleteChat, listChats } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

const PAGE = 20

export default function AllChats() {
  const [page, setPage] = useState(0)
  const queryClient = useQueryClient()
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)

  const { data, isLoading } = useQuery({
    queryKey: ['chats', 'all', page],
    queryFn: () => listChats({ limit: PAGE, offset: page * PAGE, mode: 'booops' }),
  })

  const items = data?.items ?? []
  const total = data?.total ?? 0
  const hasMore = (page + 1) * PAGE < total

  async function onDelete(e, id) {
    e.preventDefault()
    e.stopPropagation()
    if (!window.confirm('Delete this chat?')) return
    await deleteChat(id)
    await queryClient.invalidateQueries({ queryKey: ['chats'] })
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Button type="button" variant="ghost" size="icon" asChild aria-label="Back">
          <Link to={PATH_BOOOPS_HOME}>
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <h1 className="text-sm font-semibold text-foreground">All chats</h1>
      </div>
      <ScrollArea className="min-h-0 flex-1">
        <div className="mx-auto max-w-3xl space-y-1 p-3">
          {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {!isLoading && items.length === 0 && (
            <p className="text-sm text-muted-foreground">No chats yet.</p>
          )}
          {items.map((c) => (
            <div
              key={c.id}
              className={cn(
                'flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 transition-colors hover:bg-muted/40',
              )}
            >
              <Link
                to={PATH_BOOOPS_HOME}
                className="min-w-0 flex-1"
                onClick={() => {
                  setActiveChatId(c.id)
                  hydrateFromChat(c)
                }}
              >
                <p className="truncate text-sm font-medium text-foreground">{c.title || 'Untitled chat'}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {c.model} · {c.message_count ?? 0} messages
                </p>
              </Link>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label="Delete chat"
                onClick={(e) => onDelete(e, c.id)}
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      </ScrollArea>
      <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
        <Button type="button" variant="outline" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
          Previous
        </Button>
        <span className="text-xs text-muted-foreground">
          Page {page + 1} · {total} total
        </span>
        <Button type="button" variant="outline" disabled={!hasMore} onClick={() => setPage((p) => p + 1)}>
          Next
        </Button>
      </div>
    </div>
  )
}
