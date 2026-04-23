import { useEffect, useMemo, useState } from 'react'
import { Command } from 'cmdk'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import Fuse from 'fuse.js'

import { listDaws } from '@/api/daws.js'
import { listRepoTree, syncRepo } from '@/api/boocode.js'
import * as terminalsApi from '@/api/terminals.js'
import { useAppStore } from '@/store/index.js'
import { PATH_BOOCODE } from '@/routes/paths.js'

function withBase(p) {
  const base = PATH_BOOCODE.replace(/\/$/, '')
  const clean = p.startsWith('/') ? p : `/${p}`
  return base ? `${base}${clean}` : clean
}

export default function BooCodeCommandPalette() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState('root')
  const [selectionText, setSelectionText] = useState('')
  const [prevOpen, setPrevOpen] = useState(false)
  const activeDawId = useAppStore((s) => s.activeDawId)
  const navigate = useNavigate()

  // Adjust during render: reset page/selection each time the palette opens.
  if (open && !prevOpen) {
    setPrevOpen(true)
    setPage('root')
    setSelectionText('')
  } else if (!open && prevOpen) {
    setPrevOpen(false)
  }

  useEffect(() => {
    const handler = (e) => {
      const meta = e.metaKey || e.ctrlKey
      if (meta && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape' && open) {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  const { data: dawsPack } = useQuery({
    queryKey: ['daws', 'boocode'],
    queryFn: () => listDaws('boocode'),
    enabled: open,
    staleTime: 15_000,
  })
  const daws = Array.isArray(dawsPack?.items) ? dawsPack.items : []

  const { data: treePack } = useQuery({
    queryKey: ['repo-tree', activeDawId],
    queryFn: () => listRepoTree(activeDawId),
    enabled: open && Boolean(activeDawId),
    staleTime: 60_000,
  })
  const files = Array.isArray(treePack?.files) ? treePack.files : []
  const fuse = useMemo(() => new Fuse(files, { keys: ['path'], threshold: 0.4, ignoreLocation: true }), [files])
  const matches = query.trim() ? fuse.search(query.trim()).slice(0, 10).map((h) => h.item) : []

  const { data: termsPack } = useQuery({
    queryKey: ['palette-terminals', activeDawId],
    queryFn: () => terminalsApi.list({ dawId: activeDawId }),
    enabled: open && page !== 'root' && Boolean(activeDawId),
    staleTime: 5_000,
  })
  const activeTerminals = Array.isArray(termsPack?.active) ? termsPack.active : []

  const closeAnd = (fn) => () => { setOpen(false); fn?.() }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="BooCode command palette"
      className="fixed inset-0 z-[500] flex items-start justify-center pt-[16vh]"
      overlayClassName="fixed inset-0 bg-black/50"
      contentClassName="w-[min(92vw,640px)] rounded-md border p-0 shadow-2xl"
      style={{
        background: 'var(--bg-panel)',
        borderColor: 'color-mix(in srgb, var(--orange) 50%, transparent)',
        boxShadow: '0 0 0 1px color-mix(in srgb, var(--orange) 30%, transparent), var(--glow-orange)',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <div className="flex items-center gap-2 border-b px-3 py-2"
           style={{ borderColor: 'var(--border)', color: 'var(--orange)' }}>
        <span>&gt;</span>
        <Command.Input
          value={query}
          onValueChange={setQuery}
          placeholder="type a command…"
          className="w-full bg-transparent text-sm outline-none"
          style={{ color: 'var(--text)' }}
        />
      </div>
      <Command.List className="max-h-[50vh] overflow-y-auto p-2 text-sm">
        <Command.Empty className="px-3 py-2 text-xs" style={{ color: 'var(--text-dim)' }}>
          No match.
        </Command.Empty>

        {page === 'root' && (
          <>
            <Command.Group heading="ACTIONS">
              <Command.Item onSelect={closeAnd(() => navigate(withBase('/')))}>
                &gt; home
              </Command.Item>
              <Command.Item onSelect={closeAnd(() => window.dispatchEvent(new CustomEvent('boocode:new-daw')))}>
                &gt; new daw
              </Command.Item>
              {activeDawId && (
                <Command.Item onSelect={closeAnd(() => syncRepo(activeDawId).catch(() => {}))}>
                  &gt; sync current
                </Command.Item>
              )}
              {activeDawId && (
                <Command.Item onSelect={closeAnd(() => window.dispatchEvent(new CustomEvent('boocode:edit-repo-settings')))}>
                  &gt; edit repo settings
                </Command.Item>
              )}
              {activeDawId && (
                <Command.Item
                  value="new terminal"
                  onSelect={closeAnd(() => {
                    window.dispatchEvent(new CustomEvent('boocode:new-terminal', { detail: { dawId: activeDawId } }))
                  })}
                >
                  &gt; new terminal
                </Command.Item>
              )}
              {activeDawId && (
                <Command.Item
                  value="attach terminal"
                  onSelect={() => setPage('attach')}
                >
                  &gt; attach terminal…
                </Command.Item>
              )}
              {activeDawId && (
                <Command.Item
                  value="send selection to terminal"
                  onSelect={() => {
                    const sel = typeof window !== 'undefined' ? (window.getSelection()?.toString() ?? '') : ''
                    setSelectionText(sel.trim())
                    setPage('send-selection')
                  }}
                >
                  &gt; send selection to terminal…
                </Command.Item>
              )}
            </Command.Group>

            {daws.length > 0 && (
              <Command.Group heading="NAVIGATE">
                {daws.map((d) => (
                  <Command.Item key={d.id} value={`nav ${d.name}`}
                                onSelect={closeAnd(() => navigate(withBase(`/daw/${d.id}`)))}>
                    <span className="opacity-60">jump</span>&nbsp;
                    <span style={{ color: 'var(--orange)' }}>{d.name}</span>
                    {d.repo_path && <span className="ml-2 opacity-50">{d.repo_path}</span>}
                  </Command.Item>
                ))}
              </Command.Group>
            )}

            {activeDawId && matches.length > 0 && (
              <Command.Group heading="FILES">
                {matches.map((f) => (
                  <Command.Item key={f.path} value={`file ${f.path}`}
                                onSelect={closeAnd(() => {
                                  const u = new URL(window.location.href)
                                  u.searchParams.set('file', f.path)
                                  u.searchParams.delete('line')
                                  window.history.replaceState({}, '', u.toString())
                                  window.dispatchEvent(new PopStateEvent('popstate'))
                                })}>
                    <span className="opacity-60">open</span>&nbsp;
                    <span>{f.path}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </>
        )}

        {page === 'attach' && (
          <Command.Group heading="ATTACH TERMINAL">
            <Command.Item value="back" onSelect={() => setPage('root')}>
              &lt; back
            </Command.Item>
            {activeTerminals.length === 0 ? (
              <Command.Item value="__empty__" disabled>
                <span style={{ color: 'var(--text-dim)' }}>No active terminals for this DAW.</span>
              </Command.Item>
            ) : activeTerminals.map((t) => (
              <Command.Item
                key={t.id}
                value={`attach ${t.label || ''} ${t.machine_name}`}
                onSelect={closeAnd(() => {
                  window.dispatchEvent(new CustomEvent('boocode:open-terminal', { detail: { sessionId: t.id } }))
                })}
              >
                <span style={{ color: 'var(--orange)' }}>attach</span>&nbsp;
                <span>{t.label || t.machine_name || 'session'}</span>
                {t.device_count > 0 ? (
                  <span className="ml-2 inline-block size-1.5 rounded-full align-middle"
                        style={{ background: '#3cff7a' }} aria-label="attached" />
                ) : null}
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {page === 'send-selection' && (
          <Command.Group heading="SEND TO TERMINAL">
            <Command.Item value="back" onSelect={() => setPage('root')}>
              &lt; back
            </Command.Item>
            {selectionText === '' ? (
              <Command.Item value="__no-selection__" disabled>
                <span style={{ color: 'var(--text-dim)' }}>No text selected — select text first and reopen.</span>
              </Command.Item>
            ) : activeTerminals.length === 0 ? (
              <Command.Item value="__empty__" disabled>
                <span style={{ color: 'var(--text-dim)' }}>No active terminals for this DAW.</span>
              </Command.Item>
            ) : activeTerminals.map((t) => (
              <Command.Item
                key={t.id}
                value={`send ${t.label || ''} ${t.machine_name}`}
                onSelect={closeAnd(() => {
                  window.dispatchEvent(new CustomEvent('boocode:send-to-terminal', {
                    detail: { sessionId: t.id, text: selectionText, appendNewline: true },
                  }))
                })}
              >
                <span style={{ color: 'var(--orange)' }}>send →</span>&nbsp;
                <span>{t.label || t.machine_name || 'session'}</span>
                {t.device_count > 0 ? (
                  <span className="ml-2 inline-block size-1.5 rounded-full align-middle"
                        style={{ background: '#3cff7a' }} aria-label="attached" />
                ) : null}
              </Command.Item>
            ))}
          </Command.Group>
        )}
      </Command.List>
      <div className="border-t px-3 py-1.5 text-[0.625rem]"
           style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
        <span className="bc-key-hint">⏎</span> run ·
        <span className="bc-key-hint ml-1">esc</span> close
      </div>
    </Command.Dialog>
  )
}
