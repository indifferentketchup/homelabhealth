import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Copy, GitFork, Loader2 } from 'lucide-react'

import { forkChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store/index.js'

import { PersonaGlyph } from './PersonaGlyph.jsx'

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
    const mono = { fontFamily: 'var(--font-mono), ui-monospace, monospace' }
    if (inline) {
      return (
        <code
          className="fs-code rounded bg-muted px-1 py-0.5 text-[0.9em]"
          style={mono}
          {...props}
        >
          {children}
        </code>
      )
    }
    return (
      <code
        className={cn('fs-code block overflow-x-auto rounded-md border border-border bg-muted p-3', className)}
        style={mono}
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

export function MessageBubble({ chatId, message, streaming = false }) {
  const [hover, setHover] = useState(false)
  const [forkError, setForkError] = useState(null)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)
  const personaIconUrl = useAppStore((s) => s.personaIconUrl)
  const personaEmoji = useAppStore((s) => s.personaEmoji)
  const userAvatarUrl = useAppStore((s) => s.userProfile.avatarDataUrl)
  const userEmoji = useAppStore((s) => s.userProfile.emoji)
  const userDisplayName = useAppStore((s) => s.userProfile.displayName)
  const isUser = message.role === 'user'

  const userGlyph = (() => {
    const e = userEmoji && userEmoji.trim()
    if (e) return e
    return (userDisplayName && userDisplayName.trim().slice(0, 1).toUpperCase()) || 'U'
  })()

  useEffect(() => {
    if (!forkError) return
    const t = setTimeout(() => setForkError(null), 2000)
    return () => clearTimeout(t)
  }, [forkError])

  const forkMut = useMutation({
    mutationFn: () => forkChat(chatId, message.id),
    onSuccess: (newChat) => {
      setActiveChatId(newChat.id)
      hydrateFromChat(newChat)
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      navigate(PATH_BOOOPS_HOME)
    },
    onError: (err) => {
      setForkError(err instanceof Error ? err.message : 'Fork failed')
    },
  })

  async function copyText() {
    try {
      await navigator.clipboard.writeText(message.content || '')
    } catch {
      /* ignore */
    }
  }

  const canFork =
    !isUser &&
    chatId &&
    message.id &&
    message.id !== '__stream__' &&
    message.id !== '__optimistic_user__'

  return (
    <div
      className={cn('flex w-full gap-2', isUser ? 'flex-row-reverse' : 'flex-row')}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {isUser ? (
        userAvatarUrl ? (
          <img
            src={userAvatarUrl}
            alt=""
            className="mt-0.5 size-8 shrink-0 rounded-full border border-border object-cover"
            aria-hidden
          />
        ) : (
          <div
            className={cn(
              'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-muted text-xs font-medium text-muted-foreground',
              userGlyph.length > 1 && 'text-base leading-none',
            )}
            aria-hidden
          >
            {userGlyph}
          </div>
        )
      ) : (
        <PersonaGlyph kind="bubble" iconUrl={personaIconUrl} emoji={personaEmoji} className="mt-0.5" />
      )}
      <div
        className={cn(
          'flex min-w-0 max-w-[80%] flex-col',
          isUser ? 'items-end' : 'items-start',
        )}
      >
        <div
          className={cn(
            'w-fit max-w-full rounded-xl border border-border px-3 py-2',
            isUser ? 'bg-card text-foreground' : 'bg-secondary text-secondary-foreground',
          )}
        >
          {isUser ? (
            <p className="fs-chat whitespace-pre-wrap break-words leading-relaxed text-foreground">{message.content}</p>
          ) : (
            <div className="prose-chat break-words leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {message.content || (streaming ? '…' : '')}
              </ReactMarkdown>
            </div>
          )}
        </div>
        {!isUser && (
          <div
            className={cn(
              'mt-1 flex flex-col gap-1 opacity-0 transition-opacity',
              (hover || streaming) && 'opacity-100',
            )}
          >
            <div className="flex flex-wrap items-center gap-1">
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button type="button" variant="ghost" size="icon-xs" onClick={copyText} aria-label="Copy">
                      <Copy className="size-3.5" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>Copy</TooltipContent>
                </Tooltip>
                {canFork ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => forkMut.mutate()}
                        disabled={forkMut.isPending}
                        aria-label="Fork chat at this message"
                      >
                        {forkMut.isPending ? (
                          <Loader2 className="size-3.5 animate-spin opacity-70" />
                        ) : (
                          <GitFork className="size-3.5" />
                        )}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Fork here</TooltipContent>
                  </Tooltip>
                ) : null}
              </TooltipProvider>
            </div>
            {forkError ? <p className="text-xs text-destructive">{forkError}</p> : null}
          </div>
        )}
      </div>
    </div>
  )
}
