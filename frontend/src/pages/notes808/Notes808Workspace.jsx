import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Outlet, useNavigate, useParams } from 'react-router-dom'
import * as LucideIcons from 'lucide-react'

import { fetchBranding, patch808notesBranding } from '@/api/branding.js'
import { createDaw, listDaws } from '@/api/daws.js'
import { deleteSource, listSources, uploadSource } from '@/api/sources.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { FileBrowserPanel } from '@/components/FileBrowserPanel.jsx'
import { Button } from '@/components/ui/button'
import { PATH_808NOTES_HOME, notes808DawPath } from '@/routes/paths.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'

import { NotesPanel } from './NotesPanel.jsx'
import { SourcesPanel } from './SourcesPanel.jsx'

const { ChevronLeft, FolderOpen } = LucideIcons

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

function strTrim(v) {
  return typeof v === 'string' ? v.trim() : ''
}

export function Notes808Landing() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const layoutRef = useRef(null)
  const [modalOpen, setModalOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [newEmoji, setNewEmoji] = useState('🎛️')

  /**
   * Hero copy: `fetchBranding` snapshot (q) then Zustand (s). Store wins for live edits; if
   * subtitle/title are empty in the store (e.g. stale merge), keep API values so Settings saves win.
   */
  const storeBranding = useAppStore((s) => s.branding)
  const { data: brandingFromQuery } = useQuery({
    queryKey: ['branding', '808notes'],
    queryFn: () => fetchBranding('808notes'),
    staleTime: 60_000,
  })
  const branding = useMemo(() => {
    const q = brandingFromQuery && typeof brandingFromQuery === 'object' ? brandingFromQuery : {}
    const s = storeBranding && typeof storeBranding === 'object' ? storeBranding : {}
    const merged = { ...q, ...s }
    if (!strTrim(merged.subtitle) && strTrim(q.subtitle)) merged.subtitle = q.subtitle
    if (!strTrim(merged.title) && strTrim(q.title)) merged.title = q.title
    return patch808notesBranding(null, merged)
  }, [brandingFromQuery, storeBranding])

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
  /** From Settings → Branding → Subtitle / slogan (`subtitle` in API; `tagline` kept for older rows). */
  const hubTagline =
    (typeof branding?.subtitle === 'string' && branding.subtitle.trim()) ||
    (typeof branding?.tagline === 'string' && branding.tagline.trim()) ||
    ''
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
              {hubTagline ? <p className="notes808-landing__hub-tagline">{hubTagline}</p> : null}
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

export function Notes808DawLayout() {
  const { dawId } = useParams()
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const prevDawIdRef = useRef(null)

  useEffect(() => {
    if (!dawId) return
    setActiveDawId(dawId)
    if (prevDawIdRef.current !== dawId) {
      setActiveChatId(null)
      prevDawIdRef.current = dawId
    }
  }, [dawId, setActiveDawId, setActiveChatId])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <Outlet />
    </div>
  )
}

export function Notes808DawChat() {
  const { dawId } = useParams()
  const activeChatId = useAppStore((s) => s.activeChatId)
  const branding = useAppStore((s) => s.branding)
  const sidebarW = branding?.sidebarWidth ?? 260
  const [fileBrowseOpen, setFileBrowseOpen] = useState(false)

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="flex min-h-0 min-w-0 flex-1">
        <ChatView chatMode="808notes" workspaceDawId={dawId} />
      </div>
      <div
        className="hidden h-full min-h-0 shrink-0 flex-col md:flex"
        style={{ width: sidebarW }}
      >
        <div className="flex shrink-0 items-center justify-end gap-1 border-b border-sidebar-border bg-sidebar px-1 py-1">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="fs-nav h-8 gap-1 px-2"
            onClick={() => setFileBrowseOpen(true)}
          >
            <FolderOpen className="size-4" />
            Browse files
          </Button>
        </div>
        <div className="flex min-h-0 flex-[3] flex-col overflow-hidden">
          <SourcesPanel chatId={activeChatId} dawId={dawId} />
        </div>
        <div className="flex min-h-0 flex-[2] flex-col overflow-hidden border-t border-sidebar-border">
          <NotesPanel dawId={dawId} />
        </div>
      </div>
      <FileBrowserPanel
        isOpen={fileBrowseOpen}
        onClose={() => setFileBrowseOpen(false)}
        dawSyncFolder={null}
        onFileSelect={(filename, _path, content) => {
          window.dispatchEvent(
            new CustomEvent('boolab:attach-chat-file', { detail: { filename, content } }),
          )
          setFileBrowseOpen(false)
        }}
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
  const activeChatId = useAppStore((s) => s.activeChatId)
  const activeDawId = useAppStore((s) => s.activeDawId)
  const branding = useAppStore((s) => s.branding)
  const sidebarW = branding?.sidebarWidth ?? 260

  return (
    <div className="relative flex min-h-0 min-w-0 flex-1 overflow-hidden bg-background md:flex-row">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Outlet />
      </div>
      <div
        className="hidden h-full min-h-0 shrink-0 md:flex"
        style={{ width: sidebarW }}
      >
        <SourcesPanel chatId={activeChatId} dawId={activeDawId} />
      </div>
    </div>
  )
}
