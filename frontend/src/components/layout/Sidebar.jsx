import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  ChevronLeft,
  ChevronRight,
  List,
  MessageSquarePlus,
  MessagesSquare,
  PanelLeft,
  Search,
} from 'lucide-react'

import { createChat, listChats } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

export function Sidebar({ mobileOpen, onMobileOpenChange }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [isMobile, setIsMobile] = useState(false)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const apply = () => setIsMobile(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen)
  const chats = useAppStore((s) => s.chats)
  const setChats = useAppStore((s) => s.setChats)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)

  const { data } = useQuery({
    queryKey: ['chats', 'recent'],
    queryFn: () => listChats({ limit: 40, mode: 'booops' }),
    staleTime: 15_000,
  })

  useEffect(() => {
    if (data?.items) setChats(data.items)
  }, [data, setChats])

  const desktopCollapsed = !isMobile && !sidebarOpen

  async function onNewChat() {
    const chat = await createChat({ mode: 'booops' })
    await queryClient.invalidateQueries({ queryKey: ['chats'] })
    setActiveChatId(chat.id)
    hydrateFromChat(chat)
    navigate('/')
    if (isMobile) onMobileOpenChange(false)
  }

  function selectChat(id) {
    setActiveChatId(id)
    const row = chats.find((c) => c.id === id)
    if (row) hydrateFromChat(row)
    navigate('/')
    if (isMobile) onMobileOpenChange(false)
  }

  return (
    <>
      <aside
        className={cn(
          'flex h-full shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width,transform] duration-200 ease-out',
          isMobile ? 'fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw]' : 'relative z-0',
          isMobile && !mobileOpen && '-translate-x-full',
          isMobile && mobileOpen && 'translate-x-0 shadow-[var(--glow)]',
          !isMobile && (desktopCollapsed ? 'w-14' : 'w-72'),
        )}
      >
        <div className="flex items-center gap-2 border-b border-sidebar-border p-2">
          {!desktopCollapsed && (
            <div className="flex h-16 flex-1 items-center justify-center overflow-hidden rounded-md border border-sidebar-border bg-card px-2">
              <span className="truncate text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                BooOps
              </span>
            </div>
          )}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0 text-sidebar-foreground"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            aria-label={desktopCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {desktopCollapsed ? <PanelLeft className="size-4" /> : <ChevronLeft className="size-4" />}
          </Button>
        </div>

        <div className="flex flex-col gap-2 p-2">
          <Button
            type="button"
            className={cn('w-full justify-start gap-2', desktopCollapsed && 'px-0')}
            onClick={onNewChat}
            aria-label="New chat"
          >
            <MessageSquarePlus className="size-4 shrink-0" />
            {!desktopCollapsed && <span>New chat</span>}
          </Button>
          <div
            className={cn(
              'flex items-center gap-2 rounded-md border border-sidebar-border bg-card px-2 py-1.5 text-sm text-muted-foreground',
              desktopCollapsed && 'justify-center px-0',
            )}
          >
            <Search className="size-4 shrink-0" />
            {!desktopCollapsed && <span className="truncate">Search (soon)</span>}
          </div>
        </div>

        <div className="flex flex-col gap-1 px-2 pb-1">
          {!desktopCollapsed && (
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Recent chats</p>
          )}
          <Button
            type="button"
            variant="ghost"
            className={cn('h-9 w-full justify-start font-normal', desktopCollapsed && 'px-0 justify-center')}
            asChild
          >
            <Link to="/chats" onClick={() => isMobile && onMobileOpenChange(false)}>
              {!desktopCollapsed ? <span className="text-sm">All chats</span> : <List className="size-4" />}
            </Link>
          </Button>
        </div>

        <ScrollArea className="min-h-0 flex-1 px-2">
          <div className="flex flex-col gap-1 pb-2">
            {chats.map((c) => (
              <Button
                key={c.id}
                type="button"
                variant={c.id === activeChatId ? 'secondary' : 'ghost'}
                className={cn(
                  'h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal',
                  desktopCollapsed && 'px-0 justify-center',
                )}
                onClick={() => selectChat(c.id)}
                aria-current={c.id === activeChatId ? 'page' : undefined}
              >
                <MessagesSquare className="size-4 shrink-0 opacity-70" />
                {!desktopCollapsed && (
                  <span className="line-clamp-2 text-sm">{c.title || 'Untitled chat'}</span>
                )}
              </Button>
            ))}
          </div>
        </ScrollArea>

        <div className="mt-auto border-t border-sidebar-border p-2">
          <Button
            type="button"
            variant="outline"
            className={cn(
              'w-full border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent',
              desktopCollapsed && 'px-0',
            )}
            asChild
          >
            <a href="https://boolab.boogaardmusic.com" target="_blank" rel="noreferrer" title="boolab">
              {!desktopCollapsed ? (
                <span className="text-sm">boolab</span>
              ) : (
                <ChevronRight className="size-4" />
              )}
            </a>
          </Button>
        </div>
      </aside>

      {isMobile && mobileOpen && (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-background/70 md:hidden"
          aria-label="Close sidebar"
          onClick={() => onMobileOpenChange(false)}
        />
      )}
    </>
  )
}
