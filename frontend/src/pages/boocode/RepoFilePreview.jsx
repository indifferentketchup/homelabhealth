import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { X, Copy, Paperclip, WrapText } from 'lucide-react'
import { codeToTokens } from 'shiki'

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
  const [tokenLines, setTokenLines] = useState([])
  const [shikiMeta, setShikiMeta] = useState({ bg: '#0d1117', fg: '#e6edf3' })
  const containerRef = useRef(null)

  // Selection state: null | { start: number, end: number } (1-indexed, inclusive)
  const [selection, setSelection] = useState(null)
  // selectionRef lets event handlers read the latest selection without stale closures.
  // Updated in a layout effect (outside render) to satisfy the react-hooks/refs lint rule.
  const selectionRef = useRef(null)
  const dragRef = useRef(null) // { anchor: number } during drag

  useEffect(() => {
    selectionRef.current = selection
  })

  // Adjust-during-render pattern: clear selection when file path changes
  const [lastPath, setLastPath] = useState(path)
  if (path !== lastPath) {
    setLastPath(path)
    setSelection(null)
  }

  // Palette updates URL via history.replaceState + dispatchEvent(PopStateEvent).
  // React Router reads location, but without this listener the preview wouldn't
  // react to palette-driven navigation. Cheap defensive re-render.
  useEffect(() => {
    const h = () => setPopTick((n) => n + 1)
    window.addEventListener('popstate', h)
    return () => window.removeEventListener('popstate', h)
  }, [])

  // Window-level mouseup/touchend to clear drag state
  useEffect(() => {
    const onUp = () => { dragRef.current = null }
    window.addEventListener('mouseup', onUp)
    window.addEventListener('touchend', onUp)
    return () => {
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('touchend', onUp)
    }
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
    const content = data?.content
    const language = data?.language

    async function highlight() {
      if (!content) {
        if (!cancelled) setTokenLines([])
        return
      }
      const lang = (language || 'text').toLowerCase()
      try {
        const result = await codeToTokens(content, { lang, theme: 'github-dark' })
        if (!cancelled) {
          setShikiMeta({ bg: result.bg || '#0d1117', fg: result.fg || '#e6edf3' })
          setTokenLines(result.tokens)
        }
      } catch {
        if (!cancelled) {
          // Fallback: plain text, split into lines
          const lines = content.split('\n')
          setTokenLines(lines.map((l) => [{ content: l, color: undefined }]))
        }
      }
    }

    void highlight()
    return () => { cancelled = true }
  }, [data?.content, data?.language])

  // Scroll to line when `line` param changes or tokenLines load
  useEffect(() => {
    if (!line || !containerRef.current || tokenLines.length === 0) return
    const el = containerRef.current.querySelector(`[data-line="${line}"]`)
    if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [line, tokenLines])

  function handleGutterMouseDown(ln, shift) {
    if (shift && selectionRef.current) {
      setSelection({
        start: Math.min(selectionRef.current.start, ln),
        end: Math.max(selectionRef.current.end, ln),
      })
      return
    }
    dragRef.current = { anchor: ln }
    setSelection({ start: ln, end: ln })
  }

  function handleGutterMouseEnter(ln) {
    if (!dragRef.current) return
    const anchor = dragRef.current.anchor
    setSelection({ start: Math.min(anchor, ln), end: Math.max(anchor, ln) })
  }

  // Two-tap range selection on touch (no drag):
  //   Case 1: No selection → set single-line at N.
  //   Case 2: Re-tap the currently-selected single line → clear selection.
  //   Case 3: Tap inside an existing multi-line range → reset to single-line at N.
  //   Case 4: Tap outside the existing range → extend to include N.
  //
  // This gives mobile users range selection without needing Shift+tap
  // or drag gestures. Desktop shift-click is handled by handleGutterMouseDown.
  function handleGutterTouchStart(ln, e) {
    e.preventDefault()
    const cur = selectionRef.current
    if (!cur) {
      // No selection yet — start fresh.
      setSelection({ start: ln, end: ln })
      return
    }
    if (ln === cur.start && ln === cur.end) {
      // Tapping the same single-line selection deselects it.
      setSelection(null)
      return
    }
    if (ln >= cur.start && ln <= cur.end) {
      // Tapping inside an existing range resets to that single line.
      setSelection({ start: ln, end: ln })
      return
    }
    // Tapping outside extends the range.
    setSelection({
      start: Math.min(cur.start, ln),
      end: Math.max(cur.end, ln),
    })
  }

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
    const detail = { dawId, path, language: data?.language }
    if (selection) {
      detail.lineStart = selection.start
      detail.lineEnd = selection.end
    }
    window.dispatchEvent(new CustomEvent('boocode:attach-file', { detail }))
    close()
  }

  if (!open) return null
  const breadcrumb = path.split('/')

  const onBackdropMouseDown = (e) => {
    // Only close if the mousedown actually started on the backdrop itself —
    // prevents drag-to-select that happens to end outside the drawer from
    // closing the preview.
    if (e.target === e.currentTarget) close()
  }

  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-[400] flex">
      <div
        className="absolute inset-0 bg-black/25"
        onMouseDown={onBackdropMouseDown}
        aria-hidden
      />
      <div
        className="relative ml-auto flex h-full w-[1000px] max-w-[100vw] flex-col overflow-hidden border-l shadow-2xl"
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
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs whitespace-nowrap"
                    style={{ borderColor: 'var(--orange)', color: 'var(--orange)' }}>
              <Paperclip className="size-3" />
              {/* On <sm screens show "attach" + a compact badge so the header
                  row doesn't overflow on 320-375px phones. On sm+ show the
                  full "attach N-M" inline label. */}
              {selection ? (
                <>
                  <span className="sm:hidden">attach</span>
                  <span className="hidden sm:inline">{`attach ${selection.start}-${selection.end}`}</span>
                  <span className="sm:hidden rounded bg-orange-500/20 px-1 text-[0.625rem] font-semibold leading-4"
                        style={{ color: 'var(--orange)' }}>
                    {selection.start}-{selection.end}
                  </span>
                </>
              ) : 'attach'}
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
            className="flex min-h-0 flex-1 overflow-auto text-xs leading-5"
            style={{
              background: shikiMeta.bg,
              color: shikiMeta.fg,
              fontFamily: 'var(--font-mono, ui-monospace, monospace)',
              userSelect: 'text',
              WebkitUserSelect: 'text',
            }}
          >
            {isLoading && (
              <div className="p-3" style={{ color: 'var(--text-dim)' }}>loading…</div>
            )}
            {isError && (
              <div className="p-3 text-xs" style={{ color: '#ff6b6b' }}>
                {String(error?.message || 'Could not load file')}
              </div>
            )}
            {!isLoading && !isError && tokenLines.length > 0 && (
              <>
                {/* Gutter column */}
                <div
                  className="sticky left-0 shrink-0 select-none border-r border-white/10 pr-1 text-right"
                  style={{ background: shikiMeta.bg, minWidth: '3.5rem' }}
                >
                  {tokenLines.map((_, i) => {
                    const ln = i + 1
                    const inRange = selection && ln >= selection.start && ln <= selection.end
                    return (
                      <div
                        key={i}
                        className="cursor-pointer px-2 py-1 hover:text-white/60 sm:py-0"
                        style={inRange
                          ? { background: 'rgba(255,140,0,0.25)', color: 'rgba(255,255,255,0.85)' }
                          : { color: 'rgba(255,255,255,0.28)' }}
                        onMouseDown={(e) => handleGutterMouseDown(ln, e.shiftKey)}
                        onMouseEnter={() => handleGutterMouseEnter(ln)}
                        onTouchStart={(e) => handleGutterTouchStart(ln, e)}
                      >
                        {ln}
                      </div>
                    )
                  })}
                </div>
                {/* Code column */}
                <div className="flex-1 overflow-x-auto">
                  {tokenLines.map((lineTokens, i) => {
                    const ln = i + 1
                    const inRange = selection && ln >= selection.start && ln <= selection.end
                    return (
                      <div
                        key={i}
                        data-line={ln}
                        className={cn('px-3 py-1 sm:py-0', wrap && 'whitespace-pre-wrap')}
                        style={inRange ? { background: 'rgba(255,140,0,0.12)' } : undefined}
                      >
                        {lineTokens.length === 0 ? (
                          <span>{' '}</span>
                        ) : (
                          lineTokens.map((token, j) => (
                            <span key={j} style={{ color: token.color || shikiMeta.fg }}>
                              {token.content}
                            </span>
                          ))
                        )}
                      </div>
                    )
                  })}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
