import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, List, MessageSquarePlus, MessagesSquare, PanelLeft, Search } from 'lucide-react'

import { deleteChat, listChats, patchChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

export function Sidebar({ mobileOpen, onMobileOpenChange }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [isMobile, setIsMobile] = useState(false)

  const [ctx, setCtx] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const editInputRef = useRef(null)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const apply = () => setIsMobile(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (!editingId) return
    editInputRef.current?.focus()
    editInputRef.current?.select()
  }, [editingId])

  const closeCtx = useCallback(() => setCtx(null), [])

  const ctxMenuRef = useRef(null)

  useEffect(() => {
    if (!ctx) return
    const onKey = (e) => {
      if (e.key === 'Escape') closeCtx()
    }
    const onMouseDown = (e) => {
      if (
        e.target.closest('[data-radix-popper-content-wrapper]') ||
        e.target.closest('[data-radix-portal]')
      )
        return
      if (ctxMenuRef.current && !ctxMenuRef.current.contains(e.target)) {
        closeCtx()
      }
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onMouseDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onMouseDown)
    }
  }, [ctx, closeCtx])

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

  function goHome() {
    setActiveChatId(null)
    navigate('/')
    if (isMobile) onMobileOpenChange(false)
  }

  function onNewChat() {
    setActiveChatId(null)
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

  function onChatContextMenu(e, chat) {
    e.preventDefault()
    e.stopPropagation()
    setCtx({ x: e.clientX, y: e.clientY, chat })
  }

  async function commitRename(chatId) {
    const title = editTitle.trim() || 'Untitled chat'
    setEditingId(null)
    try {
      await patchChat(chatId, { title })
      setChats(chats.map((c) => (c.id === chatId ? { ...c, title } : c)))
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    }
  }

  async function commitRenameFromPrompt(chatId, title) {
    const t = title.trim() || 'Untitled chat'
    try {
      await patchChat(chatId, { title: t })
      setChats(chats.map((c) => (c.id === chatId ? { ...c, title: t } : c)))
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    }
  }

  async function onDeleteChat(chatId) {
    closeCtx()
    try {
      await deleteChat(chatId)
      setChats(chats.filter((c) => c.id !== chatId))
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
      if (activeChatId === chatId) {
        setActiveChatId(null)
        navigate('/')
      }
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    }
  }

  function startRename(chat) {
    closeCtx()
    if (desktopCollapsed) {
      const next = window.prompt('Chat title', chat.title || '')
      if (next === null) return
      void commitRenameFromPrompt(chat.id, next)
      return
    }
    setEditingId(chat.id)
    setEditTitle(chat.title || '')
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
        <div className="border-b border-sidebar-border p-2">
          {!desktopCollapsed ? (
            <Link
              to="/"
              onClick={(e) => {
                e.preventDefault()
                goHome()
              }}
              className="flex h-16 w-full shrink-0 items-center justify-center overflow-hidden rounded-md border border-sidebar-border bg-card px-2 outline-none ring-sidebar-ring focus-visible:ring-2"
            >
              <span className="truncate text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                BooOps
              </span>
            </Link>
          ) : (
            <div className="h-2 shrink-0" aria-hidden />
          )}
        </div>

        <div className="flex flex-col gap-2 p-2">
          <div className="flex gap-1">
            <Button
              type="button"
              className={cn('min-w-0 flex-1 justify-start gap-2', desktopCollapsed && 'px-0')}
              onClick={onNewChat}
              aria-label="New chat"
            >
              <MessageSquarePlus className="size-4 shrink-0" />
              {!desktopCollapsed && <span>New chat</span>}
            </Button>
            {!isMobile && (
              <Button
                type="button"
                variant="outline"
                size="icon"
                className="h-9 w-9 shrink-0 border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent"
                onClick={() => setSidebarOpen(!sidebarOpen)}
                aria-label={desktopCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              >
                {desktopCollapsed ? <PanelLeft className="size-4" /> : <ChevronLeft className="size-4" />}
              </Button>
            )}
          </div>
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
            className={cn('h-9 w-full justify-start font-normal', desktopCollapsed && 'justify-center px-0')}
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
              <div key={c.id} className="w-full">
                {editingId === c.id && !desktopCollapsed ? (
                  <input
                    ref={editInputRef}
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    className="h-9 w-full rounded-md border border-sidebar-border bg-card px-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                    onBlur={() => commitRename(c.id)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        commitRename(c.id)
                      }
                      if (e.key === 'Escape') {
                        setEditingId(null)
                      }
                    }}
                    onClick={(e) => e.stopPropagation()}
                  />
                ) : (
                  <Button
                    type="button"
                    variant={c.id === activeChatId ? 'secondary' : 'ghost'}
                    className={cn(
                      'h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal',
                      desktopCollapsed && 'px-0 justify-center',
                    )}
                    onClick={() => selectChat(c.id)}
                    onContextMenu={(e) => onChatContextMenu(e, c)}
                    aria-current={c.id === activeChatId ? 'page' : undefined}
                  >
                    <MessagesSquare className="size-4 shrink-0 opacity-70" />
                    {!desktopCollapsed && (
                      <span className="line-clamp-2 text-sm">{c.title || 'Untitled chat'}</span>
                    )}
                  </Button>
                )}
              </div>
            ))}
          </div>
        </ScrollArea>

        <div className="mt-auto flex flex-col gap-1 border-t border-sidebar-border p-2">
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

      {ctx && (
        <div
          ref={ctxMenuRef}
          role="menu"
          className="fixed z-50 min-w-[10rem] rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
          style={{ left: ctx.x, top: ctx.y }}
          onClick={(e) => e.stopPropagation()}
          onContextMenu={(e) => e.preventDefault()}
        >
          <button
            type="button"
            role="menuitem"
            className="flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left text-sm outline-none hover:bg-accent hover:text-accent-foreground"
            onClick={() => startRename(ctx.chat)}
          >
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            className="flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left text-sm text-destructive outline-none hover:bg-destructive/10"
            onClick={() => onDeleteChat(ctx.chat.id)}
          >
            Delete
          </button>
        </div>
      )}

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
