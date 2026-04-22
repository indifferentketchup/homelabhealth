import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Terminal, User, Settings, Cpu, Sparkles, Plus } from 'lucide-react'

import { listDaws } from '@/api/daws.js'
import { getRepoStatus, listRepoTree } from '@/api/boocode.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { PATH_BOOCODE } from '@/routes/paths.js'
import { cn } from '@/lib/utils'
import BooCodeNewDawModal from './BooCodeNewDawModal.jsx'

const BOOCODE_LOGO_SRC = '/api/branding/boocode/asset/logo'

function withBase(path) {
  const base = PATH_BOOCODE.replace(/\/$/, '')
  const clean = path.startsWith('/') ? path : `/${path}`
  return base ? `${base}${clean}` : clean
}

function BoocodeGogglesFallback({ className, style }) {
  return (
    <svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" fill="none"
         className={className} style={style} aria-hidden>
      <rect x="6" y="20" width="22" height="20" rx="4" stroke="currentColor" strokeWidth="2.5" />
      <rect x="36" y="20" width="22" height="20" rx="4" stroke="currentColor" strokeWidth="2.5" />
      <path d="M28 30 Q32 26 36 30" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      <circle cx="17" cy="30" r="3.5" fill="currentColor" />
      <circle cx="47" cy="30" r="3.5" fill="currentColor" />
    </svg>
  )
}

function relTime(iso) {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  const diff = Date.now() - t
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

function DawCard({ daw, onEnter }) {
  const qc = useQueryClient()
  const onHover = () => {
    qc.prefetchQuery({ queryKey: ['repo-sync-status', daw.id], queryFn: () => getRepoStatus(daw.id), staleTime: 10_000 })
    qc.prefetchQuery({ queryKey: ['repo-tree', daw.id], queryFn: () => listRepoTree(daw.id), staleTime: 60_000 })
  }
  return (
    <button
      type="button"
      className={cn('bc-card text-left', daw.repo_sync_status === 'syncing' && 'bc-scanline')}
      onMouseEnter={onHover}
      onFocus={onHover}
      onClick={onEnter}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="boocode-display truncate text-base" style={{ color: 'var(--orange)' }}>
            {daw.name}
          </div>
          <div className="mt-1 truncate font-mono text-xs" style={{ color: 'var(--text-dim)' }}>
            {daw.repo_path || '(no repo bound)'}
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[0.6875rem] font-mono"
           style={{ color: 'var(--text-dim)' }}>
        <span>branch: {daw.repo_branch || 'main'}</span>
        <span>synced: {relTime(daw.repo_last_synced_at)}</span>
      </div>
    </button>
  )
}

export default function BooCodeLanding() {
  const branding = useAppStore((s) => s.branding) || {}
  const [logoFailed, setLogoFailed] = useState(false)
  const [newOpen, setNewOpen] = useState(false)
  const [creating, setCreating] = useState(null)
  const navigate = useNavigate()

  const title = (branding.title || 'BooCode').trim() || 'BooCode'
  const subtitle = (branding.subtitle || '// architect at 3am. terminal amber, code awareness.').trim()

  const { data } = useQuery({
    queryKey: ['daws', 'boocode'],
    queryFn: () => listDaws('boocode'),
    staleTime: 15_000,
  })
  const daws = Array.isArray(data?.items) ? data.items : []

  useEffect(() => {
    const handler = () => setNewOpen(true)
    window.addEventListener('boocode:new-daw', handler)
    return () => window.removeEventListener('boocode:new-daw', handler)
  }, [])

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto" style={{ color: 'var(--text)' }}>
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-10 md:px-8 md:py-14">
        <div className="boocode-breadcrumb">BOOCODE@TERMINAL ~/project</div>

        <section
          className={cn(
            'boocode-terminal-frame flex flex-col items-center gap-6 rounded-md px-6 py-10',
            'sm:flex-row sm:items-center sm:gap-8 sm:px-10 sm:py-12',
          )}
          style={{ background: 'var(--bg-panel)' }}
        >
          <div className="flex h-40 w-40 shrink-0 items-center justify-center overflow-hidden rounded-md border sm:h-52 sm:w-52"
               style={{
                 borderColor: 'color-mix(in srgb, var(--orange) 45%, transparent)',
                 background: 'var(--bg-card)',
                 boxShadow: 'var(--glow-orange)',
               }}>
            {logoFailed ? (
              <BoocodeGogglesFallback className="h-24 w-24" style={{ color: 'var(--orange)' }} />
            ) : (
              <img src={BOOCODE_LOGO_SRC} alt="" className="h-full w-full object-cover"
                   onError={() => setLogoFailed(true)} />
            )}
          </div>

          <div className="flex min-w-0 flex-1 flex-col gap-3 text-center sm:text-left">
            <h1 className="boocode-display text-5xl md:text-6xl"
                style={{ color: 'var(--orange)', textShadow: 'var(--glow-orange)', lineHeight: 1 }}>
              {title}
            </h1>
            <p className="text-sm md:text-base"
               style={{
                 color: 'var(--text-dim)',
                 fontFamily: "'JetBrains Mono', monospace",
                 letterSpacing: '0.04em',
               }}>
              {subtitle}
            </p>
            <div className="mt-4 flex justify-center sm:justify-start">
              <Button
                type="button"
                variant="outline"
                className="uppercase tracking-[0.2em]"
                style={{
                  fontFamily: "'Orbitron', sans-serif",
                  borderColor: 'var(--orange)',
                  color: 'var(--orange)',
                  background: 'var(--bg-card)',
                  letterSpacing: '0.22em',
                }}
                onClick={() => setNewOpen(true)}
              >
                <Plus className="mr-2 size-4" />
                NEW DAW
              </Button>
            </div>
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <span className="h-px w-5 shrink-0"
                  style={{ background: 'var(--orange)', boxShadow: '0 0 4px var(--orange)' }} />
            <span className="text-[0.6875rem] uppercase tracking-[0.22em]"
                  style={{ color: 'var(--text-dim)', fontFamily: "'Orbitron', sans-serif" }}>
              DAWs
            </span>
            <span className="h-px flex-1" style={{ background: 'var(--border)' }} />
          </div>

          {daws.length === 0 && !creating ? (
            <div className="boocode-terminal-frame rounded-md px-6 py-10 text-center"
                 style={{
                   background: 'var(--bg-panel)',
                   color: 'var(--text-dim)',
                   fontFamily: "'JetBrains Mono', monospace",
                 }}>
              <Terminal className="mx-auto mb-3 size-6" style={{ color: 'var(--text-muted)' }} />
              <div className="text-sm">No BooCode DAWs yet.</div>
              <div className="mt-1 text-xs">
                <span className="bc-prompt-dollar">$</span> new daw — to begin.
              </div>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {creating && (
                <div className="bc-card bc-scanline pointer-events-none">
                  <div className="boocode-display truncate text-base bc-scramble"
                       style={{ color: 'var(--orange)' }}>
                    {creating.name}
                  </div>
                  <div className="mt-1 truncate font-mono text-xs"
                       style={{ color: 'var(--text-dim)' }}>
                    creating…<span className="bc-caret" />
                  </div>
                </div>
              )}
              {daws.map((d) => (
                <DawCard
                  key={d.id}
                  daw={d}
                  onEnter={() => navigate(withBase(`/daw/${d.id}`))}
                />
              ))}
            </div>
          )}
        </section>

        <nav className="flex flex-wrap items-center justify-center gap-2 pt-2 sm:justify-start">
          <LandingNavChip to={withBase('/profile')} icon={User} label="profile" />
          <LandingNavChip to={withBase('/ai')} icon={Cpu} label="ai" />
          <LandingNavChip to={withBase('/settings')} icon={Settings} label="settings" />
          <LandingNavChip to={withBase('/skills')} icon={Sparkles} label="skills" />
        </nav>
      </div>

      {newOpen && (
        <BooCodeNewDawModal
          onClose={() => { setNewOpen(false); setCreating(null) }}
          onStart={(v) => setCreating(v)}
          onCreated={(daw) => {
            setCreating(null)
            setNewOpen(false)
            navigate(withBase(`/daw/${daw.id}`))
          }}
        />
      )}
    </div>
  )
}

function LandingNavChip({ to, icon: Icon, label }) {
  return (
    <Link
      to={to}
      className="flex items-center gap-2 rounded-md border px-3 py-2 text-xs uppercase tracking-[0.16em] transition-colors"
      style={{
        borderColor: 'color-mix(in srgb, var(--orange) 22%, transparent)',
        background: 'var(--bg-card)',
        color: 'var(--text-dim)',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <Icon className="size-3.5" style={{ color: 'var(--orange)' }} />
      {label}
    </Link>
  )
}
