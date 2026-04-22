import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import parse from 'html-react-parser'
import { X, Copy, Paperclip, WrapText } from 'lucide-react'
import { codeToHtml } from 'shiki'

import { getRepoFile, listRepoSymbols } from '@/api/boocode.js'
import { cn } from '@/lib/utils.js'

function SymbolRail({ symbols, onJump }) {
  if (!symbols?.length) {
    return <div className="p-2 text-[0.6875rem]" style={{ color: 'var(--text-dim)' }}>No symbols.</div>
  }
  return (
    <ul className="flex flex-col gap-0.5 p-1">
      {symbols.map((s, i) => (
        <li key={i}>
          <button type="button" onClick={() => onJump(s.line_start)}
                  className="w-full truncate rounded px-1.5 py-0.5 text-left font-mono text-[0.6875rem] hover:bg-accent">
            <span className="opacity-60">{s.kind}</span>{' '}
            <span style={{ color: 'var(--orange)' }}>{s.name || '—'}</span>
            <span className="ml-1 opacity-50">@{s.line_start}</span>
          </button>
        </li>
      ))}
    </ul>
  )
}

export function RepoFilePreview({ dawId }) {
  const [params, setParams] = useSearchParams()
  const [, setPopTick] = useState(0)
  const path = params.get('file')
  const line = params.get('line')
  const open = Boolean(path)
  const [wrap, setWrap] = useState(false)
  const [shikiHtml, setShikiHtml] = useState('')
  const containerRef = useRef(null)

  // Palette updates URL via history.replaceState + dispatchEvent(PopStateEvent).
  // React Router reads location, but without this listener the preview wouldn't
  // react to palette-driven navigation. Cheap defensive re-render.
  useEffect(() => {
    const h = () => setPopTick((n) => n + 1)
    window.addEventListener('popstate', h)
    return () => window.removeEventListener('popstate', h)
  }, [])

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['repo-file', dawId, path],
    queryFn: () => getRepoFile(dawId, path),
    enabled: open && Boolean(dawId),
    staleTime: 60_000,
  })

  const { data: symData } = useQuery({
    queryKey: ['repo-symbols', dawId, path],
    queryFn: () => listRepoSymbols(dawId, path),
    enabled: open && Boolean(dawId),
    staleTime: 60_000,
  })

  useEffect(() => {
    let cancelled = false
    if (!data?.content) { setShikiHtml(''); return }
    const lang = (data.language || 'text').toLowerCase()
    codeToHtml(data.content, {
      lang,
      theme: 'github-dark',
      transformers: [{
        line(node, lineNumber) {
          node.properties['data-line'] = String(lineNumber)
        },
      }],
    }).then((out) => { if (!cancelled) setShikiHtml(out) })
      .catch(() => {
        if (!cancelled) {
          const esc = (data.content || '').replace(/[&<>]/g,
            (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
          setShikiHtml(`<pre>${esc}</pre>`)
        }
      })
    return () => { cancelled = true }
  }, [data?.content, data?.language])

  const parsedCode = useMemo(() => (shikiHtml ? parse(shikiHtml) : null), [shikiHtml])

  useEffect(() => {
    if (!line || !containerRef.current) return
    const el = containerRef.current.querySelector(`[data-line="${line}"]`)
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [line, parsedCode])

  const close = () => {
    const next = new URLSearchParams(params)
    next.delete('file'); next.delete('line')
    setParams(next, { replace: true })
  }
  const jump = (ln) => {
    const next = new URLSearchParams(params)
    next.set('line', String(ln))
    setParams(next, { replace: true })
  }
  const copyPath = () => {
    if (!path) return
    navigator.clipboard?.writeText(path).catch(() => {})
  }
  const attach = () => {
    if (!path || !dawId) return
    window.dispatchEvent(new CustomEvent('boocode:attach-file', {
      detail: { dawId, path, language: data?.language },
    }))
    close()
  }

  if (!open) return null
  const breadcrumb = path.split('/')

  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-[400] flex">
      <div className="absolute inset-0 bg-black/40" onClick={close} aria-hidden />
      <div
        className="ml-auto flex h-full w-[1000px] max-w-[100vw] flex-col overflow-hidden border-l shadow-2xl"
        style={{ background: 'var(--bg-panel)', borderColor: 'var(--border)' }}
      >
        <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2"
             style={{ borderColor: 'var(--border)' }}>
          <nav className="flex min-w-0 items-center gap-1 truncate font-mono text-xs"
               style={{ color: 'var(--text-dim)' }}>
            {breadcrumb.map((seg, i) => (
              <span key={i} className="truncate">
                {i > 0 && <span className="mx-1 opacity-50">/</span>}
                <span className={cn(i === breadcrumb.length - 1 && 'text-foreground')}>{seg}</span>
              </span>
            ))}
          </nav>
          <span className="bc-status-pill bc-status-idle">{(data?.language || '').toUpperCase() || 'TEXT'}</span>
          <div className="ml-auto flex items-center gap-1">
            <button type="button" onClick={() => setWrap((v) => !v)}
                    className={cn('rounded-md border p-1', wrap && 'bg-accent')}
                    style={{ borderColor: 'var(--border)' }} aria-label="Toggle wrap">
              <WrapText className="size-3" />
            </button>
            <button type="button" onClick={copyPath}
                    className="rounded-md border p-1" style={{ borderColor: 'var(--border)' }}
                    aria-label="Copy path">
              <Copy className="size-3" />
            </button>
            <button type="button" onClick={attach}
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs"
                    style={{ borderColor: 'var(--orange)', color: 'var(--orange)' }}>
              <Paperclip className="size-3" /> attach
            </button>
            <button type="button" onClick={close}
                    className="rounded-md border p-1" style={{ borderColor: 'var(--border)' }}
                    aria-label="Close">
              <X className="size-3" />
            </button>
          </div>
        </div>
        <div className="flex min-h-0 flex-1">
          <aside className="hidden w-56 shrink-0 overflow-y-auto border-r md:block"
                 style={{ borderColor: 'var(--border)' }}>
            <SymbolRail symbols={symData?.symbols || []} onJump={jump} />
          </aside>
          <div
            ref={containerRef}
            className={cn(
              'min-h-0 flex-1 overflow-auto font-mono text-xs',
              wrap && '[&_pre]:whitespace-pre-wrap',
              // Strip Shiki's theme background so the container's bg paints
              // uniformly top-to-bottom regardless of file length. Pad the code
              // and force it to fill the container vertically so the drawer
              // never shows a half-filled look on short files.
              '[&_pre]:!bg-transparent [&_pre]:m-0 [&_pre]:p-3 [&_pre]:min-h-full',
            )}
            style={{
              background: 'var(--bg)',
              userSelect: 'text',
              WebkitUserSelect: 'text',
            }}
          >
            {isLoading && <div className="p-3" style={{ color: 'var(--text-dim)' }}>loading…</div>}
            {isError && (
              <div className="p-3 text-xs" style={{ color: '#ff6b6b' }}>
                {String(error?.message || 'Could not load file')}
              </div>
            )}
            {!isLoading && !isError && parsedCode}
          </div>
        </div>
      </div>
    </div>
  )
}
