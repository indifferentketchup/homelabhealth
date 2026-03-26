import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom'
import * as LucideIcons from 'lucide-react'

import { fetchBranding } from '@/api/branding.js'
import { createDaw, getDaw, listDaws } from '@/api/daws.js'
import { listChats, patchChat, patchRecentChatsListCache } from '@/api/chats.js'
import { deleteSource, listSources, uploadSource } from '@/api/sources.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { Sidebar } from '@/components/layout/Sidebar.jsx'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { PATH_808NOTES, PATH_808NOTES_HOME, notes808DawPath } from '@/routes/paths.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'

import { SourcesPanel } from './SourcesPanel.jsx'

const { ChevronLeft, FileStack, Menu, MessageSquarePlus, MessagesSquare } = LucideIcons

function LandingLucide({ name, className, style }) {
  const C =
    LucideIcons[name] && typeof LucideIcons[name] === 'function'
      ? LucideIcons[name]
      : LucideIcons.Music2
  return <C className={className} style={style} aria-hidden />
}

function firstDisplayChar(name) {
  const s = (name || '?').trim() || '?'
  const arr = [...s]
  return arr[0] || '?'
}

function DawLandingIcon({ daw }) {
  if (daw.icon_url) {
    return <img src={daw.icon_url} alt="" className="notes808-landing-card__icon-img" />
  }
  const ch = firstDisplayChar(daw.name)
  return (
    <div
      className="notes808-landing-card__icon-fallback"
      style={daw?.color ? { '--notes808-daw-tint': daw.color } : undefined}
      aria-hidden
    >
      {ch}
    </div>
  )
}

function read808AccentCss() {
  try {
    const el = document.querySelector('.layout[data-mode="808notes"]') ?? document.documentElement
    const v = getComputedStyle(el).getPropertyValue('--accent').trim()
    return v || null
  } catch {
    return null
  }
}

export function Notes808Landing() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const layoutRef = useRef(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newEmoji, setNewEmoji] = useState('🎛️')

  const { data: branding } = useQuery({
    queryKey: ['branding', '808notes'],
    queryFn: () => fetchBranding('808notes'),
    staleTime: 60_000,
  })

  const { data, isLoading, isError } = useQuery({
    queryKey: ['daws', '808notes', 'landing'],
    queryFn: () => listDaws('808notes'),
    staleTime: 30_000,
  })
  const items = Array.isArray(data?.items) ? data.items : []

  const createMut = useMutation({
    mutationFn: async () => {
      const accent = read808AccentCss()
      const baseName = newName.trim() || 'Untitled DAW'
      const name =
        newEmoji.trim() && !baseName.startsWith(newEmoji.trim())
          ? `${newEmoji.trim()} ${baseName}`
          : baseName
      return createDaw({
        name,
        description: newDesc.trim() || null,
        mode: '808notes',
        ...(accent ? { color: accent } : {}),
      })
    },
    onSuccess: (row) => {
      queryClient.invalidateQueries({ queryKey: ['daws'] })
      setModalOpen(false)
      setNewName('')
      setNewDesc('')
      setNewEmoji('🎛️')
      const id = row?.id
      if (id) navigate(notes808DawPath(id))
    },
  })

  const hubTitle = (typeof branding?.title === 'string' && branding.title.trim()) || '808notes'
  const hubTagline =
    (typeof branding?.tagline === 'string' && branding.tagline.trim()) ||
    '// pick your desk. open a daw workspace.'
  const glyphName = branding?.appGlyphIcon || 'Music2'
  const bannerUrl = typeof branding?.bannerUrl === 'string' ? branding.bannerUrl.trim() : ''
  const logoUrl = typeof branding?.logoUrl === 'string' ? branding.logoUrl.trim() : ''

  return (
    <div ref={layoutRef} className="notes808-landing flex min-h-0 flex-1 flex-col overflow-auto">
      <div className="notes808-landing__shell">
        <div className="notes808-landing__banner">
          {bannerUrl ? (
            <img src={bannerUrl} alt="" className="notes808-landing__banner-img" />
          ) : (
            <div className="notes808-landing__banner-fallback" aria-hidden>
              <span className="notes808-landing__banner-fallback-badge">// 808notes</span>
            </div>
          )}
          <div className="notes808-landing-banner-grid pointer-events-none" aria-hidden />
          <div className="notes808-landing__banner-fade pointer-events-none" />
        </div>

        <header className="notes808-landing__hero">
          <div className="notes808-landing__hero-row">
            <div className="notes808-landing__logo-box">
              {logoUrl ? (
                <img src={logoUrl} alt="" className="notes808-landing__logo-img" />
              ) : (
                <div className="notes808-landing__logo-glyph">
                  <LandingLucide
                    name={glyphName}
                    className="notes808-landing__logo-icon"
                    style={{
                      color: 'var(--accent)',
                      filter: 'drop-shadow(0 0 10px color-mix(in srgb, var(--accent) 50%, transparent))',
                    }}
                  />
                </div>
              )}
            </div>
            <div className="notes808-landing__hero-text min-w-0 flex-1">
              <h1 className="notes808-landing__hub-title">{hubTitle}</h1>
              <p className="notes808-landing__hub-tagline">{hubTagline}</p>
            </div>
          </div>
          <p className="notes808-landing__intro text-muted-foreground">
            Pick a DAW to open its chat and sources, or create a new workspace.
          </p>
          <Button type="button" className="notes808-landing__cta mt-4" onClick={() => setModalOpen(true)}>
            New DAW
          </Button>
        </header>

        <section className="notes808-landing__section">
          <div className="notes808-landing__section-rule">
            <span className="notes808-landing__section-rule-accent" />
            <span className="notes808-landing__section-rule-label">workspaces</span>
            <span className="notes808-landing__section-rule-line" />
          </div>
          {isLoading && <p className="text-sm text-muted-foreground">Loading DAWs…</p>}
          {isError && <p className="text-sm text-destructive">Could not load DAWs.</p>}
          {!isLoading && !isError && items.length === 0 && (
            <p className="text-sm text-muted-foreground">No DAWs yet — create one to get started.</p>
          )}
          <div className="notes808-landing__cards">
            {items.map((d) => (
              <Link
                key={d.id}
                to={notes808DawPath(d.id)}
                className={cn(
                  'notes808-landing-card group text-card-foreground',
                  'transition-colors hover:border-accent',
                )}
                style={
                  d?.color
                    ? { '--notes808-card-tint': d.color }
                    : undefined
                }
              >
                <div className="notes808-landing-card__ribbon" aria-hidden />
                <div className="notes808-landing-card__body">
                  <DawLandingIcon daw={d} />
                  <h2 className="notes808-landing-card__name">{d.name || 'Untitled'}</h2>
                  {d.description ? (
                    <p className="notes808-landing-card__desc">{d.description}</p>
                  ) : (
                    <p className="notes808-landing-card__desc notes808-landing-card__desc--placeholder">
                      No description
                    </p>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </section>
      </div>

      {modalOpen && (
        <div className="notes808-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="notes808-new-daw-title">
          <button type="button" className="notes808-modal-backdrop" aria-label="Close" onClick={() => setModalOpen(false)} />
          <div className="notes808-modal border border-border bg-card p-6 shadow-lg">
            <h2 id="notes808-new-daw-title" className="text-lg font-semibold text-foreground">
              New DAW
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

/** Matches Tailwind `md` (Sidebar mobile breakpoint). */
function useBelowMd() {
  const [v, setV] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const apply = () => setV(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return v
}

function Notes808DawSidebar({ dawId, daw, onMobileNav }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const isNarrow = useBelowMd()
  const chats = useAppStore((s) => s.chats)
  const setChats = useAppStore((s) => s.setChats)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)
  const branding = useAppStore((s) => s.branding)
  const sidebarW = branding?.sidebarWidth ?? 260

  const [editingId, setEditingId] = useState(null)
  const [editTitle, setEditTitle] = useState('')
  const editInputRef = useRef(null)

  const { data } = useQuery({
    queryKey: ['chats', 'recent', '808notes', dawId],
    queryFn: () => listChats({ limit: 40, mode: '808notes', dawId }),
    enabled: Boolean(dawId),
    staleTime: 15_000,
  })

  useEffect(() => {
    if (data?.items) setChats(data.items)
  }, [data, setChats])

  useEffect(() => {
    if (!editingId) return
    editInputRef.current?.focus()
    editInputRef.current?.select()
  }, [editingId])

  const dawBase = notes808DawPath(dawId)
  const sourcesPath = notes808DawPath(dawId, 'sources')

  function onNewChat() {
    setActiveChatId(null)
    navigate(dawBase)
    onMobileNav?.()
  }

  function selectChat(id) {
    setActiveChatId(id)
    const row = chats.find((c) => c.id === id)
    if (row) hydrateFromChat(row)
    navigate(dawBase)
    onMobileNav?.()
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

  return (
    <aside
      className="flex h-full shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground"
      style={{ width: isNarrow ? undefined : sidebarW }}
    >
      <div className="border-b border-sidebar-border p-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="mb-2 w-full justify-start gap-2 px-2 font-normal text-muted-foreground hover:text-foreground"
          asChild
        >
          <Link to={PATH_808NOTES_HOME} onClick={() => onMobileNav?.()}>
            <ChevronLeft className="size-4 shrink-0" />
            All DAWs
          </Link>
        </Button>
        <div className="flex min-h-14 items-center gap-2 rounded-md border border-sidebar-border bg-card px-2 py-2">
          {daw?.icon_url ? (
            <img src={daw.icon_url} alt="" className="size-10 shrink-0 rounded-full object-cover" />
          ) : (
            <div
              className="flex size-10 shrink-0 items-center justify-center rounded-full text-lg font-semibold text-white"
              style={{ background: daw?.color ? daw.color : 'var(--accent)' }}
              aria-hidden
            >
              {firstDisplayChar(daw?.name)}
            </div>
          )}
          <span className="fs-nav line-clamp-2 min-w-0 flex-1 font-medium text-foreground">
            {daw?.name || '…'}
          </span>
        </div>
      </div>

      <div className="p-2">
        <Button type="button" className="fs-nav w-full justify-start gap-2" onClick={onNewChat}>
          <MessageSquarePlus className="size-4 shrink-0" />
          New Chat
        </Button>
      </div>

      <div className="mx-2 border-t border-sidebar-border" />

      <ScrollArea className="min-h-0 flex-1 px-2">
        <div className="flex flex-col gap-1 py-2 pb-8">
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
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <Button
                  type="button"
                  variant={c.id === activeChatId ? 'secondary' : 'ghost'}
                  className="h-auto min-h-9 w-full justify-start gap-2 py-2 text-left font-normal"
                  onClick={() => selectChat(c.id)}
                  onDoubleClick={() => {
                    setEditingId(c.id)
                    setEditTitle(c.title || '')
                  }}
                  aria-current={c.id === activeChatId ? 'page' : undefined}
                >
                  <MessagesSquare className="size-4 shrink-0 opacity-70" />
                  <span className="fs-nav line-clamp-2">{c.title || 'Untitled chat'}</span>
                </Button>
              )}
            </div>
          ))}
        </div>
      </ScrollArea>

      <div className="mt-auto border-t border-sidebar-border p-2">
        <Button type="button" variant="outline" className="fs-nav w-full justify-start gap-2 border-sidebar-border" asChild>
          <Link to={sourcesPath} onClick={() => onMobileNav?.()}>
            <FileStack className="size-4 shrink-0 opacity-70" />
            Sources
          </Link>
        </Button>
      </div>
    </aside>
  )
}

export function Notes808DawLayout() {
  const { dawId } = useParams()
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const isNarrow = useBelowMd()

  const { data: daw } = useQuery({
    queryKey: ['daw', dawId],
    queryFn: () => getDaw(dawId),
    enabled: Boolean(dawId),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (dawId) setActiveDawId(dawId)
    return () => {
      setActiveDawId(null)
      setActiveChatId(null)
    }
  }, [dawId, setActiveDawId, setActiveChatId])

  const modelBarProps = useMemo(() => ({ hidePersona: true, hideDaw: true }), [])
  const sourcesHref = dawId ? notes808DawPath(dawId, 'sources') : '#'

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden md:flex-row">
      {!isNarrow && <Notes808DawSidebar dawId={dawId} daw={daw} />}
      {isNarrow && mobileSidebar && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-30 bg-background/70"
            aria-label="Close sidebar"
            onClick={() => setMobileSidebar(false)}
          />
          <div className="fixed inset-y-0 left-0 z-40 w-72 max-w-[85vw] shadow-[var(--glow)]">
            <Notes808DawSidebar dawId={dawId} daw={daw} onMobileNav={() => setMobileSidebar(false)} />
          </div>
        </>
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex min-w-0 items-center gap-2 border-b border-border bg-background px-2 py-2 md:hidden">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Open sidebar"
            onClick={() => setMobileSidebar(true)}
          >
            <Menu className="size-5" />
          </Button>
          <ModelSelectorBar className="min-w-0 flex-1" {...modelBarProps} />
          <Button type="button" variant="ghost" size="icon" className="shrink-0" asChild aria-label="Sources">
            <Link to={sourcesHref}>
              <FileStack className="size-5" />
            </Link>
          </Button>
        </header>
        <main className="main flex min-h-0 flex-1 flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export function Notes808DawChat() {
  const modelBarProps = useMemo(() => ({ hidePersona: true, hideDaw: true }), [])
  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <ChatView
        chatMode="808notes"
        compactEmptyState
        modelBarProps={modelBarProps}
        hidePersonaInChatInput
      />
    </div>
  )
}

export function Notes808DawSourcesPage() {
  const { dawId } = useParams()
  const queryClient = useQueryClient()
  const fileRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [status, setStatus] = useState('')

  const { data: sources = [], isLoading } = useQuery({
    queryKey: ['sources', dawId],
    queryFn: () => listSources(dawId),
    enabled: Boolean(dawId),
    refetchInterval: (q) => {
      const rows = q.state.data
      if (!Array.isArray(rows)) return false
      return rows.some((r) => r.embedding_status === 'processing' || r.embedding_status === 'pending')
        ? 2000
        : false
    },
  })

  async function onUpload(e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !dawId) return
    setUploading(true)
    setStatus('')
    try {
      const res = await uploadSource(file, dawId)
      if (res?.status === 'already_exists') setStatus('Already ingested (same file hash).')
      else setStatus(`Ingesting ${file.name}…`)
      await queryClient.invalidateQueries({ queryKey: ['sources', dawId] })
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function onDeleteSource(id, name) {
    if (!window.confirm(`Remove source "${name}"?`)) return
    try {
      await deleteSource(id)
      await queryClient.invalidateQueries({ queryKey: ['sources', dawId] })
    } catch {
      setStatus('Delete failed')
    }
  }

  const backPath = notes808DawPath(dawId)

  return (
    <div className="notes808-sources-page flex min-h-0 flex-1 flex-col overflow-auto bg-background px-4 py-6">
      <div className="mx-auto w-full max-w-2xl">
        <Button type="button" variant="ghost" size="sm" className="mb-4 gap-1 px-0" asChild>
          <Link to={backPath}>
            <ChevronLeft className="size-4" />
            Back to chat
          </Link>
        </Button>
        <h1 className="text-lg font-semibold text-foreground">Sources</h1>
        <p className="mt-1 text-sm text-muted-foreground">Documents embedded for this DAW.</p>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,.pdf,.docx,text/plain,text/markdown,application/pdf"
            className="sr-only"
            disabled={uploading || !dawId}
            onChange={(ev) => void onUpload(ev)}
          />
          <Button
            type="button"
            disabled={uploading || !dawId}
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
          {sources.map((s) => (
            <li
              key={s.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-card px-3 py-3"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-foreground">{s.name || s.filename || 'Source'}</p>
                {s.embedding_status ? (
                  <p className="text-xs text-muted-foreground">{s.embedding_status}</p>
                ) : null}
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="shrink-0 text-destructive hover:bg-destructive/10"
                onClick={() => onDeleteSource(s.id, s.name || s.filename)}
              >
                Delete
              </Button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

export function Notes808AuxShell() {
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [mobileSourcesOpen, setMobileSourcesOpen] = useState(false)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const activeDawId = useAppStore((s) => s.activeDawId)

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const apply = () => {
      if (mq.matches) setMobileSourcesOpen(false)
    }
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (!mobileSourcesOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') setMobileSourcesOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [mobileSourcesOpen])

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden bg-background md:flex-row">
      <Sidebar
        appMode="808notes"
        routeBase={PATH_808NOTES}
        mobileOpen={mobileSidebar}
        onMobileOpenChange={(open) => {
          setMobileSidebar(open)
          if (open) setMobileSourcesOpen(false)
        }}
      />
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex min-w-0 items-center gap-2 border-b border-border bg-background px-2 py-2 md:hidden">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Open sidebar"
            onClick={() => {
              setMobileSourcesOpen(false)
              setMobileSidebar(true)
            }}
          >
            <Menu className="size-5" />
          </Button>
          <ModelSelectorBar className="min-w-0 flex-1" />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0"
            aria-label="Open sources panel"
            onClick={() => {
              setMobileSidebar(false)
              setMobileSourcesOpen(true)
            }}
          >
            <FileStack className="size-5" />
          </Button>
        </header>
        <main className="main flex min-h-0 flex-1 flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>

      {mobileSourcesOpen && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-30 bg-background/70 md:hidden"
            aria-label="Close sources panel"
            onClick={() => setMobileSourcesOpen(false)}
          />
          <div
            className="fixed inset-y-0 right-0 z-40 h-full max-w-[85vw] shadow-[var(--glow)] md:hidden"
            role="dialog"
            aria-label="Sources"
          >
            <SourcesPanel chatId={activeChatId} dawId={activeDawId} />
          </div>
        </>
      )}
    </div>
  )
}
