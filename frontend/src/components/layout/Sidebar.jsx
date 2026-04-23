import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import {
  Brain,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileStack,
  LayoutGrid,
  List,
  MessageSquarePlus,
  MessagesSquare,
  PanelLeft,
  Pin,
  Plus,
  Search,
  Settings,
  TerminalSquare,
  User,
} from 'lucide-react'

import { applyBrandingCss, fetchBranding } from '@/api/branding.js'
import { deleteChat, listChats, patchChat, patchRecentChatsListCache } from '@/api/chats.js'
import { listDaws } from '@/api/daws.js'
import * as terminalsApi from '@/api/terminals.js'
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
import {
  PATH_808NOTES,
  PATH_808NOTES_HOME,
  PATH_BOOCODE,
  PATH_BOOCODE_HOME,
  PATH_BOOOPS,
  PATH_BOOOPS_HOME,
  boocodeDawPath,
  booopsDawPath,
  getBoolabHubHref,
  isHttpUrl,
  notes808DawPath,
} from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

// ---------------------------------------------------------------------------
// BooCode per-DAW row with nested TERMINALS + CHATS subsections
// ---------------------------------------------------------------------------
function BoocodeDawRow({
  daw,
  isActive,
  isExpanded,
  onToggle,
  isMobile,
  onMobileClose,
  navigate,
  activeChatId,
  activeDawId,
  setActiveDawId,
  setActiveChatId,
  hydrateFromChat,
}) {
  const { data: terminalsData } = useQuery({
    queryKey: ['sidebar-terminals', daw.id],
    queryFn: () => terminalsApi.list({ dawId: daw.id }),
    enabled: isExpanded,
    refetchInterval: isExpanded ? 15_000 : false,
  })

  const { data: chatsData } = useQuery({
    queryKey: ['chats', 'sidebar-daw', daw.id],
    queryFn: () => listChats({ limit: 5, mode: 'boocode', dawId: daw.id }),
    enabled: isExpanded,
    staleTime: 15_000,
    refetchInterval: 30_000,
  })

  const sessions = useMemo(() => {
    const raw = Array.isArray(terminalsData?.active) ? terminalsData.active : []
    return [...raw].sort((a, b) => {
      if (a.pinned && !b.pinned) return -1
      if (!a.pinned && b.pinned) return 1
      return new Date(a.created_at) - new Date(b.created_at)
    })
  }, [terminalsData])

  const chatList = useMemo(() => {
    return Array.isArray(chatsData?.items) ? chatsData.items : []
  }, [chatsData])

  function openTerminal(sessionId) {
    window.dispatchEvent(new CustomEvent('boocode:open-terminal', { detail: { sessionId } }))
  }

  function newTerminal() {
    window.dispatchEvent(new CustomEvent('boocode:new-terminal', { detail: { dawId: daw.id } }))
  }

  function selectDawChat(c) {
    setActiveChatId(c.id)
    hydrateFromChat(c)
    setActiveDawId(daw.id)
    navigate(boocodeDawPath(daw.id))
    if (isMobile) onMobileClose()
  }

  return (
    <div className="w-full">
      {/* DAW row header */}
      <div className="flex w-full items-center gap-1 rounded-md pr-1 hover:bg-sidebar-accent/30">
        <button
          type="button"
          className="flex shrink-0 items-center justify-center rounded-sm p-1 text-muted-foreground outline-none ring-sidebar-ring hover:text-foreground focus-visible:ring-2"
          onClick={onToggle}
          aria-label={isExpanded ? 'Collapse' : 'Expand'}
        >
          <ChevronRight
            className={cn(
              'size-3.5 shrink-0 transition-transform duration-150',
              isExpanded && 'rotate-90',
            )}
            aria-hidden
          />
        </button>
        <Button
          type="button"
          variant={isActive ? 'secondary' : 'ghost'}
          className="h-auto min-h-8 flex-1 justify-start gap-2 py-1.5 text-left font-normal"
          asChild
        >
          <Link
            to={`${PATH_BOOCODE}/daw/${daw.id}`}
            onClick={() => {
              if (isMobile) onMobileClose()
            }}
            onContextMenu={(e) => {
              e.preventDefault()
              navigate(`${PATH_BOOCODE}/daws/${daw.id}`)
            }}
          >
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ background: daw.color || '#7c3aed' }}
              aria-hidden
            />
            <span className="fs-nav line-clamp-2">{daw.name}</span>
          </Link>
        </Button>
      </div>

      {/* Expanded nested sections */}
      {isExpanded && (
        <div className="ml-3 mt-0.5 flex flex-col gap-0.5 border-l border-sidebar-border pl-2">
          {/* TERMINALS subsection */}
          <div className="mt-1">
            <span className="fs-nav block px-1 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Terminals ({sessions.length})
            </span>
            {sessions.map((s) => (
              <button
                key={s.id}
                type="button"
                className="fs-nav flex w-full items-center gap-1.5 rounded-md px-1 py-1 text-left text-sm outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
                onClick={() => openTerminal(s.id)}
              >
                {s.pinned ? (
                  <Pin className="size-3.5 shrink-0 opacity-60" aria-hidden />
                ) : (
                  <TerminalSquare className="size-3.5 shrink-0 opacity-60" aria-hidden />
                )}
                <span className="min-w-0 flex-1 truncate">
                  {s.label || s.machine_name || 'session'}
                </span>
                {s.device_count > 0 && (
                  <span className="flex items-center gap-1 shrink-0">
                    <span
                      className="size-1.5 rounded-full"
                      style={{ background: '#3cff7a' }}
                      aria-label="active"
                    />
                    {s.device_count > 1 && (
                      <span className="text-[10px] text-muted-foreground">{s.device_count}</span>
                    )}
                  </span>
                )}
              </button>
            ))}
            {/* + new terminal */}
            <button
              type="button"
              className="fs-nav flex w-full items-center gap-1.5 rounded-md px-1 py-1 text-left text-xs text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
              onClick={newTerminal}
            >
              <Plus className="size-3 shrink-0 opacity-60" aria-hidden />
              <span>new terminal</span>
            </button>
          </div>

          {/* CHATS subsection */}
          <div className="mt-1">
            <span className="fs-nav block px-1 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
              Chats ({chatList.length})
            </span>
            {chatList.length === 0 ? (
              <span className="fs-nav block px-1 py-1 text-xs text-muted-foreground">
                No chats yet
              </span>
            ) : (
              chatList.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={cn(
                    'fs-nav flex w-full items-center gap-1.5 rounded-md px-1 py-1 text-left text-sm outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2',
                    c.id === activeChatId && String(activeDawId) === String(daw.id) && 'bg-sidebar-accent/60 font-medium',
                  )}
                  onClick={() => selectDawChat(c)}
                >
                  <MessagesSquare className="size-3.5 shrink-0 opacity-60" aria-hidden />
                  <span className="min-w-0 flex-1 truncate">{c.title || 'Untitled chat'}</span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// localStorage helpers for per-DAW expand state
// ---------------------------------------------------------------------------
const DAW_EXPANDED_KEY = 'bb-sidebar-daw-expanded'

function readDawExpandedMap() {
  try {
    const raw = localStorage.getItem(DAW_EXPANDED_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeDawExpandedMap(m) {
  try {
    localStorage.setItem(DAW_EXPANDED_KEY, JSON.stringify(m))
  } catch {
    /* quota / private mode — non-fatal */
  }
}

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

export function Sidebar({
  mobileOpen,
  onMobileOpenChange,
  appMode = 'booops',
  routeBase = PATH_BOOOPS,
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const boolabHubHref = getBoolabHubHref()
  const boolabHubExternal = isHttpUrl(boolabHubHref)
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

  const currentUser = useAppStore((s) => s.currentUser)
  const adminUi = true

  const sidebarOpen = useAppStore((s) => s.sidebarOpen)
  const setSidebarOpen = useAppStore((s) => s.setSidebarOpen)
  const chats = useAppStore((s) => s.chats)
  const setChats = useAppStore((s) => s.setChats)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)
  const activeDawId = useAppStore((s) => s.activeDawId)
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const branding = useAppStore((s) => s.branding)
  const sidebarW = branding?.sidebarWidth ?? 260

  const recentChatMode =
    appMode === '808notes' ? '808notes' : appMode === 'boocode' ? 'boocode' : 'booops'
  const { data } = useQuery({
    queryKey: ['chats', 'recent', recentChatMode, activeDawId ?? 'all'],
    queryFn: () =>
      listChats({
        limit: 40,
        mode: recentChatMode,
        ...(activeDawId ? { dawId: activeDawId } : {}),
      }),
    staleTime: 15_000,
    enabled: appMode === 'booops' || appMode === '808notes',
  })

  const { data: brandingRow } = useQuery({
    queryKey: ['branding', appMode],
    queryFn: () => fetchBranding(appMode),
    staleTime: 60_000,
    enabled: appMode === 'booops' || appMode === '808notes' || appMode === 'boocode',
  })

  const pinnedDawMode =
    appMode === '808notes' ? '808notes' : appMode === 'boocode' ? 'boocode' : 'booops'
  const { data: dawsListPack, isError: dawsListError } = useQuery({
    queryKey: ['daws', `pinned-sidebar-${pinnedDawMode}`],
    queryFn: () => listDaws(pinnedDawMode),
    staleTime: 30_000,
    enabled: appMode === 'booops' || appMode === '808notes' || appMode === 'boocode',
  })

  const pinnedDaws = useMemo(() => {
    const list = Array.isArray(dawsListPack?.items) ? dawsListPack.items : []
    if (appMode === 'boocode') return list
    if (appMode === '808notes') return list.filter((d) => d.pinned_808notes === true)
    return list.filter((d) => d.pinned_booops === true)
  }, [dawsListPack, appMode])

  const [pinnedOpen, setPinnedOpen] = useState(() => readSectionOpen('bb-sidebar-pinned-open', true))
  const [recentOpen, setRecentOpen] = useState(() => readSectionOpen('bb-sidebar-recent-open', true))

  // Per-DAW expand state (BooCode only)
  const [dawExpandedMap, setDawExpandedMap] = useState(() => readDawExpandedMap())

  // Persist DAW-expanded map to localStorage whenever it changes
  useEffect(() => {
    writeDawExpandedMap(dawExpandedMap)
  }, [dawExpandedMap])

  // Auto-expand active DAW on navigation — "adjust during render" pattern
  const [lastActiveDaw, setLastActiveDaw] = useState(activeDawId ?? null)
  if ((activeDawId ?? null) !== lastActiveDaw) {
    setLastActiveDaw(activeDawId ?? null)
    if (appMode === 'boocode' && activeDawId) {
      setDawExpandedMap((prev) => {
        if (prev[activeDawId]) return prev
        return { ...prev, [activeDawId]: true }
      })
    }
  }

  const toggleDawExpanded = useCallback((dawId) => {
    setDawExpandedMap((prev) => ({ ...prev, [dawId]: !prev[dawId] }))
  }, [])

  function togglePinnedOpen() {
    setPinnedOpen((o) => {
      const n = !o
      try {
        localStorage.setItem('bb-sidebar-pinned-open', String(n))
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
        localStorage.setItem('bb-sidebar-recent-open', String(n))
      } catch {
        /* ignore */
      }
      return n
    })
  }

  useEffect(() => {
    if (
      !brandingRow ||
      (appMode !== 'booops' && appMode !== '808notes' && appMode !== 'boocode')
    )
      return
    applyBrandingCss(brandingRow, appMode)
  }, [brandingRow, appMode])

  useEffect(() => {
    if (data?.items) setChats(data.items)
  }, [data, setChats])

  const desktopCollapsed = !isMobile && !sidebarOpen

  function notes808WorkspaceChatPath() {
    if (appMode === 'boocode') {
      if (activeDawId) return boocodeDawPath(activeDawId)
      return PATH_BOOCODE_HOME
    }
    if (appMode === '808notes') {
      if (activeDawId) return notes808DawPath(activeDawId)
      return PATH_808NOTES_HOME
    }
    // booops
    if (activeDawId) return booopsDawPath(activeDawId)
    return PATH_BOOOPS_HOME
  }

  function goHome() {
    if (appMode === 'booops' || appMode === '808notes' || appMode === 'boocode') {
      setActiveChatId(null)
      setActiveDawId(null)
    }
    navigate(
      appMode === '808notes'
        ? PATH_808NOTES_HOME
        : appMode === 'boocode'
          ? PATH_BOOCODE_HOME
          : PATH_BOOOPS_HOME,
    )
    if (isMobile) onMobileOpenChange(false)
  }

  function onNewChat() {
    setActiveChatId(null)
    navigate(notes808WorkspaceChatPath())
    if (isMobile) onMobileOpenChange(false)
  }

  const brandTitle =
    branding?.title ||
    (appMode === '808notes'
      ? '808notes'
      : appMode === 'boocode'
        ? 'BooCode'
        : 'BooOps')

  function selectChat(id) {
    setActiveChatId(id)
    const row = chats.find((c) => c.id === id)
    if (row) hydrateFromChat(row)
    navigate(notes808WorkspaceChatPath())
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
      const prev = useAppStore.getState().chats
      const sid = String(chatId)
      setChats(prev.map((c) => (String(c.id) === sid ? { ...c, title } : c)))
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
      const prev = useAppStore.getState().chats
      const sid = String(chatId)
      setChats(prev.map((c) => (String(c.id) === sid ? { ...c, title: t } : c)))
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
      setChats(chats.filter((c) => c.id !== chat.id))
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
      if (activeChatId === chat.id) {
        setActiveChatId(null)
        navigate(notes808WorkspaceChatPath())
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
              to={
                appMode === '808notes'
                  ? PATH_808NOTES_HOME
                  : appMode === 'boocode'
                    ? PATH_BOOCODE_HOME
                    : PATH_BOOOPS_HOME
              }
              onClick={(e) => {
                e.preventDefault()
                goHome()
              }}
              className={cn(
                'block w-full shrink-0 outline-none ring-sidebar-ring focus-visible:ring-2',
                !branding?.bannerUrl && 'p-2',
              )}
            >
              {branding?.bannerUrl ? (
                <div
                  className={cn('relative w-full overflow-hidden aspect-[3/1]')}
                >
                  <img
                    src={branding.bannerUrl}
                    alt={brandTitle}
                    className="h-full w-full object-fill"
                  />
                </div>
              ) : (
                <div className="flex min-h-16 w-full items-center justify-center overflow-hidden rounded-md border border-sidebar-border bg-card px-2">
                  <span className="fs-nav truncate text-center font-semibold uppercase tracking-wide text-muted-foreground">
                    {brandTitle}
                  </span>
                </div>
              )}
            </Link>
          ) : (
            <div className="h-2 shrink-0" aria-hidden />
          )}
        </div>

        <div className="flex flex-col gap-2 p-2">
          {(appMode === 'booops' || appMode === '808notes' || appMode === 'boocode') && (
            <>
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
              {appMode === 'booops' && (
                <div
                  className={cn(
                    'fs-nav flex items-center gap-2 rounded-md border border-sidebar-border bg-card px-2 py-1.5 text-muted-foreground',
                    desktopCollapsed && 'justify-center px-0',
                  )}
                >
                  <Search className="size-4 shrink-0" />
                  {!desktopCollapsed && <span className="truncate">Search (soon)</span>}
                </div>
              )}
            </>
          )}
        </div>

        <div className="mx-2 border-t border-sidebar-border" />

        {appMode === 'booops' ? (
          <>
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
                <Link to={`${routeBase}/chats`} onClick={() => isMobile && onMobileOpenChange(false)}>
                  {!desktopCollapsed ? (
                    <span className="fs-nav flex items-center gap-2">
                      <List className="size-4 shrink-0 opacity-70" />
                      All chats
                    </span>
                  ) : (
                    <List className="size-4" aria-hidden />
                  )}
                </Link>
              </Button>
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
                  to={appMode === 'boocode' ? (routeBase || '/') : `${routeBase}/daws`}
                  onClick={() => isMobile && onMobileOpenChange(false)}
                >
                  {!desktopCollapsed ? (
                    <span className="fs-nav flex items-center gap-2">
                      <LayoutGrid className="size-4 shrink-0 opacity-70" />
                      DAWs
                    </span>
                  ) : (
                    <LayoutGrid className="size-4" aria-hidden />
                  )}
                </Link>
              </Button>
            </div>

            <div className="mx-2 border-t border-sidebar-border" />
          </>
        ) : appMode === 'boocode' ? (
          <>
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
                  to={PATH_BOOCODE_HOME}
                  onClick={() => isMobile && onMobileOpenChange(false)}
                  aria-label="All DAWs"
                >
                  {!desktopCollapsed ? (
                    <span className="fs-nav flex items-center gap-2">
                      <LayoutGrid className="size-4 shrink-0 opacity-70" />
                      All DAWs
                    </span>
                  ) : (
                    <LayoutGrid className="size-4" aria-hidden />
                  )}
                </Link>
              </Button>
            </div>

            <div className="mx-2 border-t border-sidebar-border" />
          </>
        ) : (
          <>
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
                  to={PATH_808NOTES_HOME}
                  onClick={() => isMobile && onMobileOpenChange(false)}
                  aria-label="All DAWs"
                >
                  {!desktopCollapsed ? (
                    <span className="fs-nav flex items-center gap-2">
                      <LayoutGrid className="size-4 shrink-0 opacity-70" />
                      All DAWs
                    </span>
                  ) : (
                    <LayoutGrid className="size-4" aria-hidden />
                  )}
                </Link>
              </Button>
              {activeDawId ? (
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
                    to={notes808DawPath(activeDawId, 'sources')}
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
          </>
        )}

        <ScrollArea className="min-h-0 flex-1 px-2">
          <div className="flex flex-col gap-1 pb-2">
            {appMode === 'booops' && !desktopCollapsed && (
              <>
                <button
                  type="button"
                  onClick={togglePinnedOpen}
                  className="fs-nav flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left font-medium uppercase tracking-wide text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
                >
                  <span>Pinned DAWs</span>
                  <ChevronDown
                    className={cn(
                      'size-4 shrink-0 transition-transform duration-150',
                      !pinnedOpen && 'rotate-180',
                    )}
                    aria-hidden
                  />
                </button>
                <div className={cn(!pinnedOpen && 'h-0 overflow-hidden')}>
                  {dawsListError || pinnedDaws.length === 0 ? (
                    <span className="fs-nav block px-2 text-muted-foreground">No pinned DAWs</span>
                  ) : (
                    pinnedDaws.map((d) => (
                      <Button
                        key={d.id}
                        type="button"
                        variant="ghost"
                        className="h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal"
                        asChild
                      >
                        <Link
                          to={`${PATH_BOOOPS}/daw/${d.id}`}
                          onClick={() => {
                            if (isMobile) onMobileOpenChange(false)
                          }}
                          onContextMenu={(e) => {
                            e.preventDefault()
                            navigate(`${PATH_BOOOPS}/daws/${d.id}`)
                          }}
                        >
                          <span
                            className="size-2.5 shrink-0 rounded-full"
                            style={{ background: d.color || '#7c3aed' }}
                            aria-hidden
                          />
                          <span className="fs-nav line-clamp-2">{d.name}</span>
                        </Link>
                      </Button>
                    ))
                  )}
                </div>

                <div className="mx-0 my-1 border-t border-sidebar-border" />
              </>
            )}

            {appMode === '808notes' && !desktopCollapsed && (
              <>
                <button
                  type="button"
                  onClick={togglePinnedOpen}
                  className="fs-nav flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left font-medium uppercase tracking-wide text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
                >
                  <span>Pinned DAWs</span>
                  <ChevronDown
                    className={cn(
                      'size-4 shrink-0 transition-transform duration-150',
                      !pinnedOpen && 'rotate-180',
                    )}
                    aria-hidden
                  />
                </button>
                <div className={cn(!pinnedOpen && 'h-0 overflow-hidden')}>
                  {dawsListError || pinnedDaws.length === 0 ? (
                    <span className="fs-nav block px-2 text-muted-foreground">No pinned DAWs</span>
                  ) : (
                    pinnedDaws.map((d) => (
                      <Button
                        key={d.id}
                        type="button"
                        variant={String(d.id) === String(activeDawId) ? 'secondary' : 'ghost'}
                        className="h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal"
                        asChild
                      >
                        <Link
                          to={notes808DawPath(d.id)}
                          onClick={() => {
                            if (isMobile) onMobileOpenChange(false)
                          }}
                          onContextMenu={(e) => {
                            e.preventDefault()
                            navigate(`${PATH_808NOTES}/daws/${d.id}`)
                          }}
                        >
                          <span
                            className="size-2.5 shrink-0 rounded-full"
                            style={{ background: d.color || '#7c3aed' }}
                            aria-hidden
                          />
                          <span className="fs-nav line-clamp-2">{d.name}</span>
                        </Link>
                      </Button>
                    ))
                  )}
                </div>

                <div className="mx-0 my-1 border-t border-sidebar-border" />
              </>
            )}

            {appMode === 'boocode' && !desktopCollapsed && (
              <>
                <button
                  type="button"
                  onClick={togglePinnedOpen}
                  className="fs-nav flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left font-medium uppercase tracking-wide text-muted-foreground outline-none ring-sidebar-ring hover:bg-sidebar-accent/50 focus-visible:ring-2"
                >
                  <span>DAWs</span>
                  <ChevronDown
                    className={cn(
                      'size-4 shrink-0 transition-transform duration-150',
                      !pinnedOpen && 'rotate-180',
                    )}
                    aria-hidden
                  />
                </button>
                <div className={cn(!pinnedOpen && 'h-0 overflow-hidden')}>
                  {dawsListError || pinnedDaws.length === 0 ? (
                    <span className="fs-nav block px-2 text-muted-foreground">No DAWs</span>
                  ) : (
                    pinnedDaws.map((d) => (
                      <BoocodeDawRow
                        key={d.id}
                        daw={d}
                        isActive={String(d.id) === String(activeDawId)}
                        isExpanded={Boolean(dawExpandedMap[d.id])}
                        onToggle={() => toggleDawExpanded(d.id)}
                        isMobile={isMobile}
                        onMobileClose={() => onMobileOpenChange(false)}
                        navigate={navigate}
                        activeChatId={activeChatId}
                        activeDawId={activeDawId}
                        setActiveDawId={setActiveDawId}
                        setActiveChatId={setActiveChatId}
                        hydrateFromChat={hydrateFromChat}
                      />
                    ))
                  )}
                </div>

                <div className="mx-0 my-1 border-t border-sidebar-border" />
              </>
            )}

            {(appMode === 'booops' || appMode === '808notes') && !desktopCollapsed && (
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
                <div className={cn(!recentOpen && 'h-0 overflow-hidden')}>
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
                        <Button
                          type="button"
                          variant={c.id === activeChatId ? 'secondary' : 'ghost'}
                          className="h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal"
                          onClick={() => selectChat(c.id)}
                          onContextMenu={(e) => onChatContextMenu(e, c)}
                          aria-current={c.id === activeChatId ? 'page' : undefined}
                        >
                          <MessagesSquare className="size-4 shrink-0 opacity-70" />
                          <span className="fs-nav line-clamp-2">{c.title || 'Untitled chat'}</span>
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            {appMode === 'booops' && desktopCollapsed && (
              <div className="flex flex-col items-center gap-1 pt-1">
                {pinnedDaws.map((d) => (
                  <Link
                    key={d.id}
                    to={`${PATH_BOOOPS}/daw/${d.id}`}
                    title={d.name}
                    onClick={() => {
                      if (isMobile) onMobileOpenChange(false)
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      navigate(`${PATH_BOOOPS}/daws/${d.id}`)
                    }}
                    className="flex h-9 w-full items-center justify-center rounded-md transition-colors hover:bg-sidebar-accent/50"
                  >
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: d.color || '#7c3aed' }}
                      aria-hidden
                    />
                  </Link>
                ))}
              </div>
            )}

            {appMode === '808notes' && desktopCollapsed && (
              <div className="flex flex-col items-center gap-1 pt-1">
                {pinnedDaws.map((d) => (
                  <Link
                    key={d.id}
                    to={notes808DawPath(d.id)}
                    title={d.name}
                    onClick={() => {
                      if (isMobile) onMobileOpenChange(false)
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      navigate(`${PATH_808NOTES}/daws/${d.id}`)
                    }}
                    className={cn(
                      'flex h-9 w-full items-center justify-center rounded-md hover:bg-sidebar-accent/50',
                      String(d.id) === String(activeDawId) && 'bg-sidebar-accent/60',
                    )}
                  >
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: d.color || '#7c3aed' }}
                      aria-hidden
                    />
                  </Link>
                ))}
              </div>
            )}

            {appMode === 'boocode' && desktopCollapsed && (
              <div className="flex flex-col items-center gap-1 pt-1">
                {pinnedDaws.map((d) => (
                  <Link
                    key={d.id}
                    to={`${PATH_BOOCODE}/daw/${d.id}`}
                    title={d.name}
                    onClick={() => {
                      if (isMobile) onMobileOpenChange(false)
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault()
                      navigate(`${PATH_BOOCODE}/daws/${d.id}`)
                    }}
                    className={cn(
                      'flex h-9 w-full items-center justify-center rounded-md hover:bg-sidebar-accent/50',
                      String(d.id) === String(activeDawId) && 'bg-sidebar-accent/60',
                    )}
                  >
                    <span
                      className="size-2.5 shrink-0 rounded-full"
                      style={{ background: d.color || '#7c3aed' }}
                      aria-hidden
                    />
                  </Link>
                ))}
              </div>
            )}

            {(appMode === 'booops' || appMode === '808notes') && desktopCollapsed && (
              <div className="flex flex-col gap-1">
                {chats.map((c) => (
                  <Button
                    key={c.id}
                    type="button"
                    variant={c.id === activeChatId ? 'secondary' : 'ghost'}
                    className="h-auto min-h-9 w-full justify-center px-0 py-2 font-normal"
                    onClick={() => selectChat(c.id)}
                    onContextMenu={(e) => onChatContextMenu(e, c)}
                    aria-current={c.id === activeChatId ? 'page' : undefined}
                    title={c.title || 'Untitled chat'}
                  >
                    <MessagesSquare className="size-4 shrink-0 opacity-70" />
                  </Button>
                ))}
              </div>
            )}
          </div>
        </ScrollArea>

        <div className="mt-auto flex flex-col gap-1 border-t border-sidebar-border p-2">
          {(appMode === 'booops' || appMode === '808notes' || appMode === 'boocode') && currentUser && (
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
                to={`${routeBase}/profile`}
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
          {(appMode === 'booops' || appMode === '808notes' || appMode === 'boocode') && (() => {
            const showAi = currentUser?.role === 'owner'
            const showSettings = adminUi
            if (!showAi && !showSettings) return null
            const aiBtn = showAi ? (
              <Button
                key="ai"
                type="button"
                variant="outline"
                className={cn(
                  'border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent',
                  desktopCollapsed ? 'w-full px-0' : 'min-w-0 flex-1',
                )}
                asChild
              >
                <Link to={`${routeBase}/ai`} onClick={() => isMobile && onMobileOpenChange(false)} title="AI settings">
                  {!desktopCollapsed ? (
                    <span className="fs-nav flex items-center justify-center gap-2">
                      <Brain className="size-4 shrink-0" />
                      AI
                    </span>
                  ) : (
                    <Brain className="size-4" />
                  )}
                </Link>
              </Button>
            ) : null
            const settingsBtn = showSettings ? (
              <Button
                key="settings"
                type="button"
                variant="outline"
                className={cn(
                  'border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent',
                  desktopCollapsed ? 'w-full px-0' : 'min-w-0 flex-1',
                )}
                asChild
              >
                <Link
                  to={`${routeBase}/settings`}
                  onClick={() => isMobile && onMobileOpenChange(false)}
                  title="Settings"
                  aria-label="Settings"
                >
                  {!desktopCollapsed ? (
                    <span className="fs-nav flex items-center justify-center gap-2">
                      <Settings className="size-4 shrink-0" />
                      Settings
                    </span>
                  ) : (
                    <Settings className="size-4" />
                  )}
                </Link>
              </Button>
            ) : null
            return desktopCollapsed ? (
              <>
                {aiBtn}
                {settingsBtn}
              </>
            ) : (
              <div className="flex gap-1">
                {aiBtn}
                {settingsBtn}
              </div>
            )
          })()}
          <Button
            type="button"
            variant="outline"
            className={cn(
              'w-full border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent',
              desktopCollapsed && 'px-0',
            )}
            asChild
          >
            {boolabHubExternal ? (
              <a href={boolabHubHref} title="boolab">
                {!desktopCollapsed ? (
                  <span className="fs-nav">boolab</span>
                ) : (
                  <ChevronRight className="size-4" />
                )}
              </a>
            ) : (
              <Link to={boolabHubHref} title="boolab">
                {!desktopCollapsed ? (
                  <span className="fs-nav">boolab</span>
                ) : (
                  <ChevronRight className="size-4" />
                )}
              </Link>
            )}
          </Button>
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
