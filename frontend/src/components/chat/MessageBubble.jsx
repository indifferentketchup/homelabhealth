import { Children, useEffect, useMemo, useState } from 'react'
import { useLongPress } from '@/hooks/useLongPress.js'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { BookmarkPlus, Check, Copy, GitFork, Loader2, Pencil, RefreshCw } from 'lucide-react'

import { forkChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import { PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store/index.js'
import { useShallow } from 'zustand/react/shallow'

import { PersonaGlyph } from './PersonaGlyph.jsx'
import { SendToTerminalMenu } from './SendToTerminalMenu.jsx'

function CodeBlockShell({ language, rawText, chatMode, children }) {
  const [copied, setCopied] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [menuAnchor, setMenuAnchor] = useState(null)

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(rawText || '')
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore */
    }
  }

  function handleContextMenu(e) {
    if (chatMode !== 'boocode') return
    e.preventDefault()
    setMenuAnchor({ x: e.clientX, y: e.clientY })
    setMenuOpen(true)
  }

  const lp = useLongPress(handleContextMenu)

  return (
    <div
      className="group/code mb-2 last:mb-0 overflow-hidden rounded-md border border-border bg-muted"
      onContextMenu={handleContextMenu}
      onTouchStart={lp.onTouchStart}
      onTouchMove={lp.onTouchMove}
      onTouchEnd={lp.onTouchEnd}
      onTouchCancel={lp.onTouchCancel}
      style={{ WebkitTouchCallout: 'none' }}
    >
      <div className="flex items-center justify-between gap-2 border-b border-border bg-background/30 px-3 py-1">
        <span className="fs-code font-mono text-[0.7rem] uppercase tracking-wide text-muted-foreground">
          {language || 'code'}
        </span>
        <button
          type="button"
          onClick={copyCode}
          aria-label={copied ? 'Copied' : 'Copy code'}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs text-muted-foreground outline-none transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring"
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      {children}
      {chatMode === 'boocode' && (
        <SendToTerminalMenu
          open={menuOpen}
          onOpenChange={setMenuOpen}
          anchor={menuAnchor}
          text={rawText || ''}
        />
      )}
    </div>
  )
}

function extractCodeText(node) {
  if (node == null) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractCodeText).join('')
  if (node.props?.children != null) return extractCodeText(node.props.children)
  return ''
}

function makeMdComponents({ chatMode } = {}) {
  return {
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
      const mobileCodeSize = 'max-[600px]:!text-[0.85rem]'
      if (inline) {
        return (
          <code
            className={cn(
              'fs-code max-w-full [overflow-wrap:anywhere] break-words rounded bg-muted px-1 py-0.5 text-[0.9em]',
              mobileCodeSize,
            )}
            style={mono}
            {...props}
          >
            {children}
          </code>
        )
      }
      return (
        <code
          className={cn(
            'fs-code block w-full min-w-0 max-w-full [overflow-wrap:anywhere] whitespace-pre-wrap break-words bg-transparent p-3',
            mobileCodeSize,
            className,
          )}
          style={mono}
          {...props}
        >
          {children}
        </code>
      )
    },
    pre: ({ children }) => {
      const first = Children.toArray(children)[0]
      const cls = first?.props?.className || ''
      const lang = cls.match(/language-([\w-]+)/)?.[1] || null
      const rawText = extractCodeText(first).replace(/\n$/, '')
      return (
        <CodeBlockShell language={lang} rawText={rawText} chatMode={chatMode}>
          <pre
            className={cn(
              'm-0 block w-full min-w-0 max-w-full overflow-x-auto whitespace-pre-wrap break-words [overflow-wrap:anywhere]',
              'max-[600px]:max-h-[300px] max-[600px]:overflow-auto max-[600px]:!text-[0.85rem]',
            )}
          >
            {children}
          </pre>
        </CodeBlockShell>
      )
    },
    h1: ({ children }) => <h1 className="mb-2 text-lg font-semibold">{children}</h1>,
    h2: ({ children }) => <h2 className="mb-2 text-base font-semibold">{children}</h2>,
    h3: ({ children }) => <h3 className="mb-1 text-sm font-semibold">{children}</h3>,
    blockquote: ({ children }) => (
      <blockquote className="mb-2 border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>
    ),
  }
}

function formatTimestamp(isoString) {
  if (!isoString) return null
  const d = new Date(isoString)
  if (isNaN(d)) return null
  const now = new Date()
  const isToday =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  if (isToday) {
    return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()
  }
  return (
    d.toLocaleDateString([], { month: 'short', day: 'numeric' }) +
    ', ' +
    d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()
  )
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1 py-1" aria-label="Assistant is typing">
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground" />
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:150ms]" />
      <span className="size-1.5 animate-pulse rounded-full bg-muted-foreground [animation-delay:300ms]" />
    </span>
  )
}

export function MessageBubble({
  chatId,
  message,
  streaming = false,
  chatMode,
  onSaveMessageAsNote,
  onEditUser,
  onRegenerate,
}) {
  const mdComponents = useMemo(() => makeMdComponents({ chatMode }), [chatMode])
  const [hover, setHover] = useState(false)
  const [forkError, setForkError] = useState(null)
  const [editing, setEditing] = useState(false)
  const [editDraft, setEditDraft] = useState('')
  const [copied, setCopied] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const {
    setActiveChatId,
    hydrateFromChat,
    personaIconUrl,
    personaEmoji,
    profileIconObjectUrl,
    userAvatarUrl,
    userEmoji,
    userDisplayName,
  } = useAppStore(
    useShallow((s) => ({
      setActiveChatId: s.setActiveChatId,
      hydrateFromChat: s.hydrateFromChat,
      personaIconUrl: s.personaIconUrl,
      personaEmoji: s.personaEmoji,
      profileIconObjectUrl: s.profileIconObjectUrl,
      userAvatarUrl: s.userProfile.avatarDataUrl,
      userEmoji: s.userProfile.emoji,
      userDisplayName: s.userProfile.displayName,
    })),
  )
  const userImgSrc = profileIconObjectUrl || userAvatarUrl
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
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* ignore */
    }
  }

  const isPersistedMessage =
    chatId &&
    message.id &&
    message.id !== '__stream__' &&
    message.id !== '__optimistic_user__' &&
    message.id !== '__pending__'
  const isPendingTyping = message.id === '__pending__'
  const canFork = !isUser && isPersistedMessage
  const canRegenerate = Boolean(onRegenerate && canFork && !streaming)
  const canEditUser = Boolean(onEditUser && isUser && isPersistedMessage)
  const canSaveAsNote = Boolean(onSaveMessageAsNote && canFork && !streaming)
  const tsLabel = formatTimestamp(message.created_at)

  function startEdit() {
    setEditDraft(message.content || '')
    setEditing(true)
  }
  function cancelEdit() {
    setEditing(false)
    setEditDraft('')
  }
  async function commitEdit() {
    const next = editDraft.trim()
    if (!next || !onEditUser) {
      cancelEdit()
      return
    }
    setEditing(false)
    await onEditUser(message, next)
  }

  return (
    <div
      className={cn('flex w-full gap-2', isUser ? 'flex-row-reverse' : 'flex-row')}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {isUser ? (
        userImgSrc ? (
          <img
            src={userImgSrc}
            alt=""
            loading="lazy"
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
          'flex min-w-0 max-w-[80%] max-[430px]:max-w-[92%] overflow-x-hidden flex-col',
          isUser ? 'items-end' : 'items-start',
        )}
      >
        <div
          className={cn(
            'w-full min-w-0',
            isUser
              ? 'rounded-2xl border-0 bg-secondary/60 px-4 py-2.5 text-foreground'
              : 'border-l-2 border-accent/30 py-1 pl-3 text-foreground',
          )}
        >
          {isUser ? (
            editing ? (
              <div className="flex flex-col gap-2">
                <textarea
                  value={editDraft}
                  onChange={(e) => setEditDraft(e.target.value)}
                  rows={Math.min(10, Math.max(2, editDraft.split('\n').length + 1))}
                  className="fs-chat w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-foreground outline-none ring-ring focus-visible:ring-2"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault()
                      void commitEdit()
                    }
                    if (e.key === 'Escape') {
                      e.preventDefault()
                      cancelEdit()
                    }
                  }}
                />
                <div className="flex justify-end gap-2">
                  <Button type="button" size="sm" variant="ghost" onClick={cancelEdit}>
                    Cancel
                  </Button>
                  <Button type="button" size="sm" onClick={() => void commitEdit()}>
                    Save & resend
                  </Button>
                </div>
              </div>
            ) : (
              <p className="fs-chat whitespace-pre-wrap break-words leading-relaxed text-foreground">{message.content}</p>
            )
          ) : isPendingTyping ? (
            <TypingDots />
          ) : (
            <div className="prose-chat w-full max-w-full overflow-x-hidden break-words leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                {message.content || (streaming ? '' : '')}
              </ReactMarkdown>
              {streaming && (
                <span className="inline-block w-[2px] h-[1em] bg-foreground animate-pulse align-text-bottom ml-0.5" />
              )}
              {streaming && message.content ? (
                <div className="mt-1 inline-flex items-center gap-1.5 rounded-full border border-border bg-background/40 px-2 py-0.5 text-[0.7rem] text-muted-foreground">
                  <TypingDots />
                  <span>streaming</span>
                </div>
              ) : null}
            </div>
          )}
        </div>
        {tsLabel ? (
          <p
            className={`mt-0.5 text-xs text-muted-foreground/70 ${message.role === 'user' ? 'text-right' : 'text-left'}`}
          >
            {tsLabel}
          </p>
        ) : null}
        {isUser && canEditUser && !editing ? (
          <div
            className={cn(
              'mt-1 flex justify-end opacity-0 transition-opacity',
              hover && 'opacity-100',
            )}
          >
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={startEdit}
                    aria-label="Edit and resend"
                  >
                    <Pencil className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Edit & resend</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        ) : null}
        {!isUser && !isPendingTyping && (
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
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon-xs"
                      onClick={copyText}
                      aria-label={copied ? 'Copied' : 'Copy'}
                    >
                      {copied ? (
                        <Check className="size-3.5 text-primary" />
                      ) : (
                        <Copy className="size-3.5" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>{copied ? 'Copied' : 'Copy'}</TooltipContent>
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
                {canSaveAsNote ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => onSaveMessageAsNote?.(message.content)}
                        aria-label="Save as note"
                      >
                        <BookmarkPlus className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Save as note</TooltipContent>
                  </Tooltip>
                ) : null}
                {canRegenerate ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        onClick={() => onRegenerate?.(message)}
                        aria-label="Regenerate response"
                      >
                        <RefreshCw className="size-3.5" />
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>Regenerate</TooltipContent>
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
