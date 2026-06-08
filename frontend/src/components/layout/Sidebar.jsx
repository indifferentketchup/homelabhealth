import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  Brain,
  ChevronDown,
  ChevronLeft,
  FileStack,
  LayoutGrid,
  MessageSquarePlus,
  MessagesSquare,
  PanelLeft,
  Phone,
  Settings,
  User,
} from 'lucide-react'

import {
  deleteChat,
  listChats,
  patchChat,
  patchRecentChatsListCache,
  removeChatFromRecentListCache,
} from '@/api/chats.js'
import { listWorkspaces } from '@/api/workspaces.js'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ScrollArea } from '@/components/ui/scroll-area'
import { APP_TITLE } from '@/config/identity.js'
import { PATH_HOME, workspacePath } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'
import { cn } from '@/lib/utils'
import { useLongPress } from '@/hooks/useLongPress.js'
import ThemeToggle from '@/components/layout/ThemeToggle'

// ---------------------------------------------------------------------------
// Subcomponents for long-press parity on touch devices
// ---------------------------------------------------------------------------

/**
 * Single recent-chat row — extracts useLongPress out of .map().
 *
 * Memoized so a title patch (or any sidebar re-render) only re-renders the rows
 * whose props actually changed. The recent-chats Query (single source of truth)
 * preserves object identity for unchanged rows when patched, so the default
 * shallow comparison skips them; the `onSelect`/`onContextMenu` handlers are
 * stabilized with useCallback in the parent so they don't defeat the memo.
 */
const ChatRow = memo(function ChatRow({ chat, activeChatId, onSelect, onContextMenu, collapsed }) {
  const lp = useLongPress((e) => onContextMenu(e, chat))
  const isActive = chat.id === activeChatId
  return (
    <Button
      type="button"
      variant={isActive ? 'secondary' : 'ghost'}
      className={
        collapsed
          ? 'h-auto min-h-9 w-full justify-center px-0 py-2 font-normal'
          : 'h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal'
      }
      style={{ WebkitTouchCallout: 'none' }}
      onClick={() => onSelect(chat)}
      onContextMenu={(e) => onContextMenu(e, chat)}
      onTouchStart={lp.onTouchStart}
      onTouchMove={lp.onTouchMove}
      onTouchEnd={lp.onTouchEnd}
      onTouchCancel={lp.onTouchCancel}
      aria-current={isActive ? 'page' : undefined}
      title={collapsed ? (chat.title || 'Untitled chat') : undefined}
    >
      <MessagesSquare className="size-4 shrink-0 opacity-70" />
      {!collapsed && (
        <span className="fs-nav line-clamp-2">{chat.title || 'Untitled chat'}</span>
      )}
    </Button>
  )
})

// ---------------------------------------------------------------------------
// localStorage helpers for section open/closed
// ---------------------------------------------------------------------------
function readSectionOpen(key, defaultOpen) {
  try {
    const v = localStorage.getItem(key)
    if (v === null) return defaultOpen
    return v === 'true'
  } catch {
    return defaultOpen
  }
}

export function Sidebar({ mobileOpen, onMobileOpenChange }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [isMobile, setIsMobile] = useState(false)

  const [ctx, setCtx] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const [pendingDelete, setPendingDelete] = useState(null)
  const [deleting, setDeleting] = useState(false)
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

  useEffect(() => {
    if (!ctx) return
    const items = ctxMenuRef.current?.querySelectorAll('[role="menuitem"]')
    if (items && items.length > 0) items[0].focus()
  }, [ctx])

  function onCtxMenuKeyDown(e) {
    const items = Array.from(ctxMenuRef.current?.querySelectorAll('[role="menuitem"]') ?? [])
    if (!items.length) return
    const idx = items.indexOf(document.activeElement)
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      items[(idx + 1) % items.length].focus()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      items[(idx - 1 + items.length) % items.length].focus()
    } else if (e.key === 'Home') {
      e.preventDefault()
      items[0].focus()
    } else if (e.key === 'End') {
      e.preventDefault()
      items[items.length - 1].focus()
    }
  }

  const currentUser = useAppStore((s) => s.currentUser)

  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId)
  const setActiveWorkspaceId = useAppStore((s) => s.setActiveWorkspaceId)
  const sidebarW = useLayoutStore((s) => s.sidebarWidth) || 260

  const { data } = useQuery({
    queryKey: ['chats', 'recent', activeWorkspaceId ?? 'all'],
    queryFn: () =>
      listChats({
        limit: 40,
        ...(activeWorkspaceId ? { workspaceId: activeWorkspaceId } : {}),
      }),
    staleTime: 15_000,
  })

  // The recent-chats Query is the single source of truth for the displayed list.
  const chats = data?.items ?? []

  const { data: workspacesListPack, isError: workspacesListError } = useQuery({
    queryKey: ['workspaces', 'pinned-sidebar'],
    queryFn: () => listWorkspaces(),
    staleTime: 30_000,
  })

  const pinnedWorkspaces = useMemo(() => {
    const list = Array.isArray(workspacesListPack?.items) ? workspacesListPack.items : []
    return list.filter((d) => d.pinned === true)
  }, [workspacesListPack])

  const [pinnedOpen, setPinnedOpen] = useState(() => readSectionOpen('hlh-sidebar-pinned-open', true))
  const [recentOpen, setRecentOpen] = useState(() => readSectionOpen('hlh-sidebar-recent-open', true))

  function togglePinnedOpen() {
    setPinnedOpen((o) => {
      const n = !o
      try {
        localStorage.setItem('hlh-sidebar-pinned-open', String(n))
      } catch {
        /* ignore */
      }
      return n
    })
  }

  function toggleRecentOpen() {
    setRecentOpen((o) => {
      const n = !o
      try {
        localStorage.setItem('hlh-sidebar-recent-open', String(n))
      } catch {
        /* ignore */
      }
      return n
    })
  }

  const desktopCollapsed = !isMobile && !sidebarOpen

  function workspaceChatPath() {
    if (activeWorkspaceId) return workspacePath(activeWorkspaceId)
    return PATH_HOME
  }

  function goHome() {
    setActiveChatId(null)
    setActiveWorkspaceId(null)
    navigate(PATH_HOME)
    if (isMobile) onMobileOpenChange(false)
  }

  function onNewChat() {
    setActiveChatId(null)
    navigate(workspaceChatPath())
    if (isMobile) onMobileOpenChange(false)
  }

  const brandTitle = APP_TITLE

  // Stable identity (no `chats` dependency — the row passes its own chat object) so
  // memoized ChatRows aren't re-rendered on every sidebar update.
  const selectChat = useCallback(
    (chat) => {
      setActiveChatId(chat.id)
      if (chat) hydrateFromChat(chat)
      navigate(activeWorkspaceId ? workspacePath(activeWorkspaceId) : PATH_HOME)
      if (isMobile) onMobileOpenChange(false)
    },
    [setActiveChatId, hydrateFromChat, navigate, activeWorkspaceId, isMobile, onMobileOpenChange],
  )

  const onChatContextMenu = useCallback((e, chat) => {
    e.preventDefault()
    e.stopPropagation()
    setCtx({ x: e.clientX, y: e.clientY, chat })
  }, [])

  async function commitRename(chatId) {
    const title = editTitle.trim() || 'Untitled chat'
    setEditingId(null)
    try {
      await patchChat(chatId, { title })
      patchRecentChatsListCache(queryClient, chatId, title)
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    }
  }

  async function commitRenameFromPrompt(chatId, title) {
    const t = title.trim() || 'Untitled chat'
    try {
      await patchChat(chatId, { title: t })
      patchRecentChatsListCache(queryClient, chatId, t)
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    }
  }

  function requestDeleteChat(chat) {
    closeCtx()
    setPendingDelete(chat)
  }

  async function confirmDeleteChat() {
    const chat = pendingDelete
    if (!chat) return
    setDeleting(true)
    try {
      await deleteChat(chat.id)
      removeChatFromRecentListCache(queryClient, chat.id)
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
      if (activeChatId === chat.id) {
        setActiveChatId(null)
        navigate(workspaceChatPath())
      }
    } catch {
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } finally {
      setDeleting(false)
      setPendingDelete(null)
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
          !isMobile && desktopCollapsed && 'w-14',
        )}
        style={!isMobile ? { width: desktopCollapsed ? undefined : sidebarW } : undefined}
      >
        <div className="border-b border-sidebar-border">
          {!desktopCollapsed ? (
            <Link
              to={PATH_HOME}
              onClick={(e) => {
                e.preventDefault()
                goHome()
              }}
              className="block w-full shrink-0 p-2 outline-none ring-sidebar-ring focus-visible:ring-2"
            >
              <div className="flex min-h-16 w-full items-center justify-center overflow-hidden rounded-md border border-sidebar-border bg-card px-2">
                <span className="fs-nav truncate text-center font-semibold uppercase tracking-wide text-muted-foreground">
                  {brandTitle}
                </span>
              </div>
            </Link>
          ) : (
            <div className="h-2 shrink-0" aria-hidden />
          )}
        </div>

        <div className="flex flex-col gap-2 p-2">
          <div className="flex gap-1">
            <Button
              type="button"
              className={cn('fs-nav min-w-0 flex-1 justify-start gap-2', desktopCollapsed && 'px-0')}
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
        </div>

        <div className="mx-2 border-t border-sidebar-border" />

        <div className="flex flex-col gap-1 px-2 py-2">
          <Button
            type="button"
            variant="ghost"
            className={cn(
              'fs-nav h-9 w-full justify-start font-normal',
              desktopCollapsed && 'justify-center px-0',
            )}
            asChild
          >
            <Link
              to={PATH_HOME}
              onClick={() => isMobile && onMobileOpenChange(false)}
              aria-label="All workspaces"
            >
              {!desktopCollapsed ? (
                <span className="fs-nav flex items-center gap-2">
                  <LayoutGrid className="size-4 shrink-0 opacity-70" />
                  All workspaces
                </span>
              ) : (
                <LayoutGrid className="size-4" aria-hidden />
              )}
            </Link>
          </Button>
          {activeWorkspaceId ? (
            <Button
              type="button"
              variant="ghost"
              className={cn(
                'fs-nav h-9 w-full justify-start font-normal',
                desktopCollapsed && 'justify-center px-0',
              )}
              asChild
            >
              <Link
                to={workspacePath(activeWorkspaceId, 'sources')}
                onClick={() => isMobile && onMobileOpenChange(false)}
                aria-label="Sources"
              >
                {!desktopCollapsed ? (
                  <span className="fs-nav flex items-center gap-2">
                    <FileStack className="size-4 shrink-0 opacity-70" />
                    Sources
                  </span>
                ) : (
                  <FileStack className="size-4" aria-hidden />
                )}
              </Link>
            </Button>
          ) : null}
        </div>

        <div className="mx-2 border-t border-sidebar-border" />

        <ScrollArea className="min-h-0 flex-1 px-2">
          <div className="flex flex-col gap-1 pb-2">
            {!desktopCollapsed && (
              <>
                <button
                  type="button"
                  onClick={togglePinnedOpen}
                  className="fs-nav flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left font-medium uppercase tracking-wide text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
                >
                  <span>Pinned workspaces</span>
                  <ChevronDown
                    className={cn(
                      'size-4 shrink-0 transition-transform duration-150',
                      !pinnedOpen && 'rotate-180',
                    )}
                    aria-hidden
                  />
                </button>
                <div className={cn('grid transition-[grid-template-rows] duration-200 ease-out', pinnedOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                  <div className="overflow-hidden min-h-0">
                  {workspacesListError || pinnedWorkspaces.length === 0 ? (
                    <span className="fs-nav block px-2 text-muted-foreground">No pinned workspaces</span>
                  ) : (
                    pinnedWorkspaces.map((d) => (
                      <Button
                        key={d.id}
                        type="button"
                        variant={String(d.id) === String(activeWorkspaceId) ? 'secondary' : 'ghost'}
                        className="h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal"
                        asChild
                      >
                        <Link
                          to={workspacePath(d.id)}
                          aria-current={String(d.id) === String(activeWorkspaceId) ? 'page' : undefined}
                          onClick={() => {
                            if (isMobile) onMobileOpenChange(false)
                          }}
                          onContextMenu={(e) => {
                            e.preventDefault()
                            navigate(`/workspaces/${d.id}`)
                          }}
                        >
                          <span
                            className="size-2.5 shrink-0 rounded-full"
                            style={{ background: d.color || 'var(--accent-workspace)' }}
                            aria-hidden
                          />
                          <span className="fs-nav line-clamp-2">{d.name}</span>
                        </Link>
                      </Button>
                    ))
                  )}
                </div>
                </div>

                <div className="mx-0 my-1 border-t border-sidebar-border" />
              </>
            )}

            {!desktopCollapsed && (
              <>
                <button
                  type="button"
                  onClick={toggleRecentOpen}
                  className="fs-nav flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left font-medium uppercase tracking-wide text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
                >
                  <span>Recent chats</span>
                  <ChevronDown
                    className={cn(
                      'size-4 shrink-0 transition-transform duration-150',
                      !recentOpen && 'rotate-180',
                    )}
                    aria-hidden
                  />
                </button>
                <div className={cn('grid transition-[grid-template-rows] duration-200 ease-out', recentOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
                  <div className="overflow-hidden min-h-0">
                  {chats.map((c) => (
                    <div key={c.id} className="w-full">
                      {editingId === c.id ? (
                        <input
                          ref={editInputRef}
                          value={editTitle}
                          onChange={(e) => setEditTitle(e.target.value)}
                          className="fs-nav h-9 w-full rounded-md border border-sidebar-border bg-card px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
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
                        <ChatRow
                          chat={c}
                          activeChatId={activeChatId}
                          onSelect={selectChat}
                          onContextMenu={onChatContextMenu}
                          collapsed={false}
                        />
                      )}
                    </div>
                  ))}
                </div>
                </div>
              </>
            )}

            {desktopCollapsed && (
              <div className="flex flex-col items-center gap-1 pt-1">
                {pinnedWorkspaces.map((d) => (
                  <Link
                    key={d.id}
                    to={workspacePath(d.id)}
                    title={d.name}
                    aria-label={d.name}
                    aria-current={String(d.id) === String(activeWorkspaceId) ? 'page' : undefined}
                    onClick={() => {
                      if (isMobile) onMobileOpenChange(false)
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      navigate(`/workspaces/${d.id}`)
                    }}
                    className={cn(
                      'flex h-9 w-full items-center justify-center rounded-md hover:bg-sidebar-accent/50',
                      String(d.id) === String(activeWorkspaceId) && 'bg-sidebar-accent/60',
                    )}
                  >
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: d.color || 'var(--accent-workspace)' }}
                      aria-hidden
                    />
                  </Link>
                ))}
              </div>
            )}

            {desktopCollapsed && (
              <div className="flex flex-col gap-1">
                {chats.map((c) => (
                  <ChatRow
                    key={c.id}
                    chat={c}
                    activeChatId={activeChatId}
                    onSelect={selectChat}
                    onContextMenu={onChatContextMenu}
                    collapsed={true}
                  />
                ))}
              </div>
            )}
          </div>
        </ScrollArea>

        <div className="mt-auto flex flex-col gap-1 border-t border-sidebar-border p-2">
          {!desktopCollapsed && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 px-2.5 py-2 text-[11px]">
              <div className="mb-1 flex items-center gap-1.5 font-semibold text-destructive">
                <Phone className="size-3" />
                Crisis Resources
              </div>
              <div className="space-y-0.5 text-muted-foreground">
                <div className="flex justify-between"><span>988 Lifeline</span><a href="tel:988" className="font-mono font-semibold text-destructive hover:underline">988</a></div>
                <div className="flex justify-between"><span>Poison Control</span><a href="tel:18002221222" className="font-mono font-semibold text-destructive hover:underline">1-800-222-1222</a></div>
                <div className="flex justify-between"><span>Emergency</span><a href="tel:911" className="font-mono font-semibold text-destructive hover:underline">911</a></div>
              </div>
            </div>
          )}
          {desktopCollapsed && (
            <a href="tel:988" title="Crisis Resources — 988 Lifeline" className="flex justify-center py-1 text-destructive hover:text-destructive/80">
              <Phone className="size-4" />
            </a>
          )}
          <div className="flex justify-center py-1">
            <ThemeToggle />
          </div>
          {currentUser && (
            <Button
              type="button"
              variant="outline"
              className={cn(
                'w-full border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent',
                desktopCollapsed && 'px-0',
              )}
              asChild
            >
              <Link
                to="/profile"
                onClick={() => isMobile && onMobileOpenChange(false)}
                title="Profile"
                aria-label="Profile"
              >
                {!desktopCollapsed ? (
                  <span className="fs-nav flex items-center justify-center gap-2">
                    <User className="size-4 shrink-0" />
                    Profile
                  </span>
                ) : (
                  <User className="size-4" />
                )}
              </Link>
            </Button>
          )}

          {desktopCollapsed ? (
            <>
              <Button
                type="button"
                variant="outline"
                className="w-full border-sidebar-border bg-card px-0 text-foreground hover:bg-sidebar-accent"
                asChild
              >
                <Link to="/ai" onClick={() => isMobile && onMobileOpenChange(false)} title="AI settings">
                  <Brain className="size-4" />
                </Link>
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full border-sidebar-border bg-card px-0 text-foreground hover:bg-sidebar-accent"
                asChild
              >
                <Link to="/settings" onClick={() => isMobile && onMobileOpenChange(false)} title="Settings" aria-label="Settings">
                  <Settings className="size-4" />
                </Link>
              </Button>
            </>
          ) : (
            <div className="flex gap-1">
              <Button
                type="button"
                variant="outline"
                className="min-w-0 flex-1 border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent"
                asChild
              >
                <Link to="/ai" onClick={() => isMobile && onMobileOpenChange(false)} title="AI settings">
                  <span className="fs-nav flex items-center justify-center gap-2">
                    <Brain className="size-4 shrink-0" />
                    AI
                  </span>
                </Link>
              </Button>
              <Button
                type="button"
                variant="outline"
                className="min-w-0 flex-1 border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent"
                asChild
              >
                <Link to="/settings" onClick={() => isMobile && onMobileOpenChange(false)} title="Settings" aria-label="Settings">
                  <span className="fs-nav flex items-center justify-center gap-2">
                    <Settings className="size-4 shrink-0" />
                    Settings
                  </span>
                </Link>
              </Button>
            </div>
          )}
        </div>
      </aside>

      {ctx && (
        <div
          ref={ctxMenuRef}
          role="menu"
          className="fixed z-50 min-w-[10rem] rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
          style={{
            left: Math.min(ctx.x, window.innerWidth - 180),
            top: Math.min(ctx.y, window.innerHeight - 200),
          }}
          onClick={(e) => e.stopPropagation()}
          onContextMenu={(e) => e.preventDefault()}
          onKeyDown={onCtxMenuKeyDown}
        >
          <button
            type="button"
            role="menuitem"
            className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left outline-none hover:bg-accent hover:text-accent-foreground"
            onClick={() => startRename(ctx.chat)}
          >
            Rename
          </button>
          <button
            type="button"
            role="menuitem"
            className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-1.5 text-left text-destructive outline-none hover:bg-destructive/10"
            onClick={() => requestDeleteChat(ctx.chat)}
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

      <Dialog
        open={Boolean(pendingDelete)}
        onOpenChange={(open) => {
          if (!open && !deleting) setPendingDelete(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete chat?</DialogTitle>
            <DialogDescription>
              {pendingDelete
                ? `"${pendingDelete.title || 'Untitled chat'}" will be permanently deleted. This cannot be undone.`
                : ''}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={deleting}
              onClick={() => setPendingDelete(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={deleting}
              onClick={confirmDeleteChat}
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </>
  )
}
