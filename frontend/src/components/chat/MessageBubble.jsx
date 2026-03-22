import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Copy, GitBranch } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

const mdComponents = {
  p: ({ children }) => <p className="mb-2 last:mb-0 text-foreground">{children}</p>,
  ul: ({ children }) => <ul className="mb-2 list-disc pl-4 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal pl-4 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="text-foreground">{children}</li>,
  a: ({ href, children }) => (
    <a href={href} className="text-primary underline underline-offset-2" target="_blank" rel="noreferrer">
      {children}
    </a>
  ),
  code: ({ className, children, ...props }) => {
    const inline = !className
    if (inline) {
      return (
        <code className="rounded bg-muted px-1 py-0.5 font-mono text-[0.9em]" {...props}>
          {children}
        </code>
      )
    }
    return (
      <code
        className={cn('block overflow-x-auto rounded-md border border-border bg-muted p-3 font-mono text-xs', className)}
        {...props}
      >
        {children}
      </code>
    )
  },
  pre: ({ children }) => <pre className="mb-2 overflow-x-auto last:mb-0">{children}</pre>,
  h1: ({ children }) => <h1 className="mb-2 text-lg font-semibold">{children}</h1>,
  h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
  h3: ({ children }) => <h3 className="mb-1 text-sm font-semibold">{children}</h3>,
  blockquote: ({ children }) => (
    <blockquote className="mb-2 border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>
  ),
}

export function MessageBubble({ message, streaming = false }) {
  const [hover, setHover] = useState(false)
  const isUser = message.role === 'user'

  async function copyText() {
    try {
      await navigator.clipboard.writeText(message.content || '')
    } catch {
      /* ignore */
    }
  }

  return (
    <div
      className={cn('group flex w-full gap-2', isUser ? 'flex-row-reverse' : 'flex-row')}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div
        className={cn(
          'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-xs font-medium text-muted-foreground',
        )}
        aria-hidden
      >
        {isUser ? 'U' : 'W'}
      </div>
      <div className={cn('flex min-w-0 max-w-[min(100%,48rem)] flex-1 flex-col', isUser ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'rounded-xl border border-border px-3 py-2',
            isUser ? 'bg-card text-foreground' : 'bg-secondary text-secondary-foreground',
          )}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{message.content}</p>
          ) : (
            <div className="prose-chat text-sm leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {message.content || (streaming ? '…' : '')}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {!isUser && (
          <div
            className={cn(
              'mt-1 flex gap-1 opacity-0 transition-opacity',
              (hover || streaming) && 'opacity-100',
            )}
          >
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-xs" onClick={copyText} aria-label="Copy">
                    <Copy className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Copy</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-xs" disabled aria-label="Fork (soon)">
                    <GitBranch className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Fork (soon)</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        )}
      </div>
    </div>
  )
}
