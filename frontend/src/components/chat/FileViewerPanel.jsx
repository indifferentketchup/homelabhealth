import { useEffect, useRef, useState } from 'react'
import { createHighlighter } from 'shiki'
import { ChevronLeft } from 'lucide-react'

import { Button } from '@/components/ui/button'

/**
 * @param {object} props
 * @param {{ filename: string, path: string } | null} props.file
 * @param {() => void} props.onClose
 * @param {(p: { filename: string, content: string }) => void} props.onAttachLines
 */
export function FileViewerPanel({ file, onClose, onAttachLines }) {
  const highlighterRef = useRef(null)
  const [highlighterReady, setHighlighterReady] = useState(false)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [tokenLines, setTokenLines] = useState([])
  const shikiMeta = { bg: '#0d1117', fg: '#e6edf3' }
  const [truncated, setTruncated] = useState(false)
  const [selectedLines, setSelectedLines] = useState([])
  const [retryNonce, setRetryNonce] = useState(0)
  const lastClickedRef = useRef(null)
  const textRef = useRef('')

  useEffect(() => {
    createHighlighter({
      themes: ['github-dark'],
      langs: [
        'javascript',
        'jsx',
        'typescript',
        'tsx',
        'python',
        'go',
        'yaml',
        'json',
        'bash',
        'markdown',
        'css',
        'html',
        'sql',
        'dockerfile',
        'toml',
        'plaintext',
      ],
    }).then((h) => {
      highlighterRef.current = h
      setHighlighterReady(true)
    })
  }, [])

  useEffect(() => {
    if (!file?.path) return
    setSelectedLines([])
    lastClickedRef.current = null
    setError(null)
    setTokenLines([])
    setTruncated(false)

    // File preview backend is currently disconnected -- show inert state.
    textRef.current = ''
    setLoading(false)
    setError('Preview unavailable.')
  }, [file?.path, file?.filename, highlighterReady, retryNonce])

  function handleLineClick(lineNum, isShift) {
    if (isShift && lastClickedRef.current !== null) {
      const start = Math.min(lastClickedRef.current, lineNum)
      const end = Math.max(lastClickedRef.current, lineNum)
      setSelectedLines(Array.from({ length: end - start + 1 }, (_, i) => start + i))
    } else {
      setSelectedLines((prev) => (prev.length === 1 && prev[0] === lineNum ? [] : [lineNum]))
      lastClickedRef.current = lineNum
    }
  }

  function handleAttach() {
    if (!textRef.current || selectedLines.length === 0) return
    const lines = textRef.current.split('\n')
    const start = Math.min(...selectedLines)
    const end = Math.max(...selectedLines)
    const slice = lines.slice(start - 1, end).join('\n')
    onAttachLines({
      filename: `${file.filename}:${start}-${end}`,
      content: slice,
    })
    setSelectedLines([])
  }

  if (!file) return null

  const selMin = selectedLines.length ? Math.min(...selectedLines) : null
  const selMax = selectedLines.length ? Math.max(...selectedLines) : null

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="sticky top-0 z-10 flex shrink-0 items-center gap-2 border-b border-sidebar-border bg-sidebar px-2 py-1">
        <Button type="button" size="sm" variant="ghost" className="h-7 gap-1 px-2" onClick={onClose}>
          <ChevronLeft className="size-3.5" />
          Back
        </Button>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
          {file.filename}
        </span>
        {selectedLines.length > 0 && selMin != null && selMax != null && (
          <>
            <span className="shrink-0 text-xs text-muted-foreground">
              Lines {selMin}–{selMax}
            </span>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              className="h-7 shrink-0 px-2 text-xs"
              onClick={handleAttach}
            >
              Attach to chat
            </Button>
          </>
        )}
      </div>

      {truncated && (
        <div className="shrink-0 bg-yellow-500/10 px-3 py-1 text-xs text-yellow-400">
          Large file — showing first 5000 lines only
        </div>
      )}

      {loading && (
        <div className="flex flex-1 items-center justify-center text-xs text-muted-foreground">
          Loading...
        </div>
      )}

      {error && !loading && (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 text-xs text-destructive">
          <span>Error: {error}</span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setError(null)
              setTokenLines([])
              setRetryNonce((n) => n + 1)
            }}
          >
            Retry
          </Button>
        </div>
      )}

      {!loading && !error && tokenLines.length > 0 && (
        <div
          className="flex min-h-0 flex-1 overflow-auto text-xs leading-5"
          style={{
            background: shikiMeta.bg,
            color: shikiMeta.fg,
            fontFamily: 'var(--font-mono, ui-monospace, monospace)',
          }}
        >
          <div
            className="sticky left-0 shrink-0 select-none border-r border-white/10 pr-1 text-right"
            style={{ background: shikiMeta.bg, minWidth: '3.5rem' }}
          >
            {tokenLines.map((_, i) => {
              const lineNum = i + 1
              const selected = selectedLines.includes(lineNum)
              return (
                <div
                  key={i}
                  className="cursor-pointer px-2 hover:text-white/60"
                  style={
                    selected
                      ? { background: 'rgba(99,102,241,0.25)', color: 'rgba(255,255,255,0.8)' }
                      : { color: 'rgba(255,255,255,0.2)' }
                  }
                  onClick={(e) => handleLineClick(lineNum, e.shiftKey)}
                >
                  {lineNum}
                </div>
              )
            })}
          </div>

          <div className="flex-1 overflow-x-auto">
            {tokenLines.map((lineTokens, i) => {
              const lineNum = i + 1
              const selected = selectedLines.includes(lineNum)
              return (
                <div
                  key={i}
                  className="px-3"
                  style={selected ? { background: 'rgba(99,102,241,0.15)' } : undefined}
                >
                  {lineTokens.length === 0 ? (
                    <span>{'\u00A0'}</span>
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
        </div>
      )}
    </div>
  )
}
