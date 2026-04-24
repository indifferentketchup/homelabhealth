import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ArrowLeft, Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useFxSuppress } from '@/hooks/useBoocodeFx.jsx'
import { PATH_BOOCODE_HOME } from '@/routes/paths.js'

const MD_COMPONENTS = {
  h1: ({ node, ...p }) => (
    <h1
      className="mt-2 mb-3 text-2xl font-semibold tracking-wide"
      style={{ color: 'var(--orange, #ff8c00)', fontFamily: "'Orbitron', sans-serif" }}
      {...p}
    />
  ),
  h2: ({ node, ...p }) => (
    <h2
      className="mt-8 mb-2 border-t border-border pt-6 text-xl font-semibold tracking-wide"
      style={{ color: 'var(--orange, #ff8c00)', fontFamily: "'Orbitron', sans-serif" }}
      {...p}
    />
  ),
  h3: ({ node, ...p }) => (
    <h3 className="mt-5 mb-2 text-base font-semibold tracking-wide text-foreground" {...p} />
  ),
  p: ({ node, ...p }) => <p className="my-2 leading-relaxed text-foreground" {...p} />,
  ul: ({ node, ...p }) => <ul className="my-2 ml-5 list-disc space-y-1 text-foreground" {...p} />,
  ol: ({ node, ...p }) => <ol className="my-2 ml-5 list-decimal space-y-1 text-foreground" {...p} />,
  li: ({ node, ...p }) => <li className="leading-relaxed" {...p} />,
  a: ({ node, ...p }) => (
    <a
      className="underline underline-offset-2 hover:opacity-80"
      style={{ color: 'var(--orange, #ff8c00)' }}
      target="_blank"
      rel="noreferrer noopener"
      {...p}
    />
  ),
  blockquote: ({ node, ...p }) => (
    <blockquote
      className="my-2 border-l-2 pl-3 italic"
      style={{
        borderColor: 'var(--orange, #ff8c00)',
        color: 'var(--text-dim, #94a3b8)',
      }}
      {...p}
    />
  ),
  hr: () => <hr className="my-6 border-border" />,
  table: ({ node, ...p }) => (
    <div className="my-3 overflow-x-auto">
      <table className="min-w-full border-collapse text-xs" {...p} />
    </div>
  ),
  th: ({ node, ...p }) => (
    <th
      className="border border-border px-2 py-1 text-left font-semibold"
      style={{ background: 'var(--bg-card)' }}
      {...p}
    />
  ),
  td: ({ node, ...p }) => <td className="border border-border px-2 py-1 align-top" {...p} />,
  code: ({ node, inline, className, children, ...props }) => {
    if (inline) {
      return (
        <code
          className="rounded px-1 py-0.5 text-[0.875em]"
          style={{
            background: 'var(--bg-card)',
            fontFamily: "'JetBrains Mono', monospace",
            color: 'var(--orange, #ff8c00)',
          }}
          {...props}
        >
          {children}
        </code>
      )
    }
    return (
      <code className={className} {...props}>
        {children}
      </code>
    )
  },
  pre: ({ node, ...p }) => (
    <pre
      className="my-3 overflow-x-auto rounded border px-3 py-2 text-xs leading-relaxed"
      style={{
        background: 'var(--bg-panel, #0a0a0a)',
        borderColor: 'var(--border)',
        fontFamily: "'JetBrains Mono', monospace",
      }}
      {...p}
    />
  ),
}

export default function BooCodeSpecPage() {
  useFxSuppress({ matrix: true, crt: true })
  const navigate = useNavigate()
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch('/spec.md', { credentials: 'same-origin' })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.text()
      })
      .then((text) => {
        if (!cancelled) setContent(text)
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || 'Failed to load spec')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const body = useMemo(() => {
    if (error) {
      return (
        <div className="rounded border px-3 py-2 text-sm" style={{ borderColor: '#ff6b6b', color: '#ff6b6b' }}>
          Could not load spec: {error}
        </div>
      )
    }
    if (content == null) {
      return (
        <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-dim)' }}>
          <Loader2 className="size-4 animate-spin" />
          Loading…
        </div>
      )
    }
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MD_COMPONENTS}>
        {content}
      </ReactMarkdown>
    )
  }, [content, error])

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto bg-background"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    >
      <header
        className="sticky top-0 z-10 flex items-center gap-2 border-b border-border px-4 py-2"
        style={{ background: 'var(--bg-panel, #0a0a0a)' }}
      >
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => navigate(PATH_BOOCODE_HOME)}
          className="h-8"
        >
          <ArrowLeft className="mr-1 size-4" />
          Back
        </Button>
        <div
          className="ml-2 text-xs tracking-[0.2em]"
          style={{ color: 'var(--orange, #ff8c00)', fontFamily: "'Orbitron', sans-serif" }}
        >
          SPEC
        </div>
        <a
          href="/spec.md"
          className="ml-auto text-xs underline underline-offset-2 hover:opacity-80"
          style={{ color: 'var(--text-dim)' }}
        >
          view raw
        </a>
      </header>
      <article className="mx-auto w-full max-w-3xl px-6 py-6 text-sm">{body}</article>
    </div>
  )
}
