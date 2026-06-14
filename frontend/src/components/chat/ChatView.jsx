import { useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Download } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'

import { getChat, listMessages } from '@/api/chats.js'
import { createNote } from '@/api/notes.js'
import { getDurableStreamingSetting } from '@/api/settings.js'
import { useStreamOrchestrator } from '@/hooks/useStreamOrchestrator.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

import { AssistantGlyph } from './AssistantGlyph.jsx'
import { ChatInput } from './ChatInput.jsx'
import { ContextIndicator } from './ContextIndicator.jsx'
import { DisclaimerBanner } from './DisclaimerBanner.jsx'
import { MessageList } from './MessageList.jsx'
import { WorkspaceTitle } from './WorkspaceTitle.jsx'
import { StaleStreamBanner } from './StaleStreamBanner.jsx'
import { StreamStatusBar } from './StreamStatusBar.jsx'

const WORKSPACE_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

const EXPORT_THINKING_RE = /<THINKING>[\s\S]*?<\/THINKING>\s*/g

function downloadConversation(messages, chatTitle) {
  const exportable = messages.filter(
    (m) => (m.role === 'user' || m.role === 'assistant') &&
           m.id !== '__optimistic_user__' &&
           m.id !== '__stream__' &&
           m.id !== '__pending__',
  )
  if (exportable.length === 0) return
  const sections = exportable.map((m) => {
    const raw = (m.content || '').replace(EXPORT_THINKING_RE, '').trim()
    const label = m.role === 'user' ? '**You**' : '**Assistant**'
    return `${label}\n\n${raw}`
  })
  const md = sections.join('\n\n---\n\n')
  const blob = new Blob([md], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${(chatTitle || 'conversation').replace(/[^a-z0-9-_ ]/gi, '_')}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// Wire-contract spec error strings — must render verbatim with a navigable path to fix.
// These bypass friendlyStreamError's paraphrase branches and fall through as-is; we
// handle them here to surface a settings link alongside the instructional text.
function renderSendError(msg, resolvedWorkspaceId) {
  if (!msg) return null
  if (msg.includes('No provider configured for this workspace.')) {
    const href = resolvedWorkspaceId ? `/workspaces/${resolvedWorkspaceId}` : '/workspaces'
    return (
      <>
        No provider configured for this workspace.{' '}
        <Link to={href} className="underline underline-offset-2">Open Settings → Workspace</Link>{' '}
        to pick one.
      </>
    )
  }
  if (msg.includes('Embedding model not configured.')) {
    return (
      <>
        Embedding model not configured.{' '}
        <Link to="/settings" className="underline underline-offset-2">Set one in Settings → Embedding.</Link>
      </>
    )
  }
  if (msg.includes('embedding dimension mismatch')) {
    return (
      <>
        {msg}{' '}
        <Link to="/settings" className="underline underline-offset-2">Open Settings → Embedding</Link>{' '}
        to fix.
      </>
    )
  }
  return msg
}

function MessageListSkeleton() {
  const rows = [
    { role: 'assistant', w: ['w-5/6', 'w-3/4', 'w-2/3'] },
    { role: 'user', w: ['w-2/5'] },
    { role: 'assistant', w: ['w-4/5', 'w-3/5'] },
    { role: 'user', w: ['w-1/3'] },
    { role: 'assistant', w: ['w-5/6', 'w-2/3', 'w-1/2'] },
  ]
  return (
    <div
      className="flex h-full flex-col gap-4 overflow-hidden px-4 py-4"
      role="status"
      aria-label="Loading messages"
    >
      {rows.map((r, i) => {
        const isUser = r.role === 'user'
        return (
          <div
            key={i}
            className={cn('flex w-full gap-2 animate-pulse', isUser ? 'flex-row-reverse' : 'flex-row')}
            style={{ animationDelay: `${i * 80}ms` }}
          >
            <div className="mt-0.5 size-8 shrink-0 rounded-full bg-muted" aria-hidden />
            <div className={cn('flex min-w-0 max-w-[80%] flex-col gap-1.5', isUser ? 'items-end' : 'items-start')}>
              <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-secondary/40 px-3 py-2">
                {r.w.map((w, j) => (
                  <div key={j} className={cn('h-3 rounded bg-muted', w)} />
                ))}
              </div>
              <div className="h-2 w-10 rounded bg-muted/70" />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function normalizeWorkspaceUuid(raw) {
  if (raw == null || raw === '') return null
  const s = String(raw).trim()
  return WORKSPACE_UUID_RE.test(s) ? s : null
}

export function ChatView({
  /** When set (e.g. `/workspace/:id`), used if Zustand `activeWorkspaceId` is stale so new chats still attach to the workspace. */
  workspaceId: workspaceIdProp = null,
}) {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const workspaceFromQuery = normalizeWorkspaceUuid(searchParams.get('workspace'))
  const resolvedWorkspaceId = normalizeWorkspaceUuid(workspaceIdProp) || workspaceFromQuery
  const chatMaxW = useLayoutStore((s) => s.chatMaxWidth) || 1200
  const activeChatId = useAppStore((s) => s.activeChatId)
  const selectedModel = useAppStore((s) => s.selectedModel)
  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)

  const { data: chat } = useQuery({
    queryKey: ['chat', activeChatId],
    queryFn: () => getChat(activeChatId),
    enabled: Boolean(activeChatId),
  })

  useEffect(() => {
    if (chat) hydrateFromChat(chat)
  }, [chat, hydrateFromChat])

  const notesWorkspaceIdForSave = resolvedWorkspaceId ?? null

  const saveMessageAsNote = useCallback(
    async (text) => {
      const wid = notesWorkspaceIdForSave
      if (!wid) return
      const body = String(text ?? '').trim()
      if (!body) return
      await createNote(wid, { content: body, source_type: 'ai_response' })
      await queryClient.invalidateQueries({ queryKey: ['notes', wid] })
    },
    [notesWorkspaceIdForSave, queryClient],
  )

  const { data: msgPack, isLoading } = useQuery({
    queryKey: ['messages', activeChatId],
    queryFn: () => listMessages(activeChatId),
    enabled: Boolean(activeChatId),
  })

  const messages = msgPack?.items ?? []
  const chatTitle = chat?.title || null

  const { data: durableConfig } = useQuery({
    queryKey: ['settings', 'durable-streaming'],
    queryFn: getDurableStreamingSetting,
    staleTime: 5 * 60_000,
  })
  const durableEnabled = durableConfig?.enabled === true

  // The orchestrator owns both streaming protocols (SSE + durable) behind one interface.
  // ChatView is presentational: it feeds context in and renders what comes back.
  const orch = useStreamOrchestrator({
    durableEnabled,
    activeChatId,
    setActiveChatId,
    messages,
    selectedModel,
    webSearchEnabled,
    resolvedWorkspaceId,
    hydrateFromChat,
  })

  const busy = orch.busy

  const [ariaLiveText, setAriaLiveText] = useState('')
  useEffect(() => {
    if (!busy) {
      setAriaLiveText('')
      return
    }
    const text = orch.streamingTail || ''
    const timer = setTimeout(() => {
      setAriaLiveText(text.slice(-100))
    }, 300)
    return () => clearTimeout(timer)
  }, [busy, orch.streamingTail])

  const latestAssistant = [...(messages || [])].reverse().find(m => m.role === 'assistant' && m.prompt_tokens)
  const promptTokens = latestAssistant?.prompt_tokens
  const ctxMax = chat?.ctx_max

  const anchorExtraPx =
    (busy && orch.phase ? 52 : 0)
    + (orch.stale && busy ? 56 : 0)
    + (orch.sendError ? 44 : 0)

  if (!activeChatId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background">
        <WorkspaceTitle />
        <div
          className="flex min-h-0 flex-1 flex-col overflow-y-auto items-center justify-center gap-8 px-4 py-8 pt-[20vh] md:pt-0"
          style={{
            paddingBottom:
              'max(0px, calc(120px + max(env(safe-area-inset-bottom, 0px), var(--bc-keyboard-pad, 0px))))',
          }}
        >
          <div className="flex w-full flex-col items-center gap-4" style={{ maxWidth: chatMaxW }}>
            <AssistantGlyph kind="header" />
            <h1 className="fs-heading text-center font-semibold tracking-tight text-foreground">Assistant</h1>
            <div className="flex flex-wrap justify-center gap-2">
              {[
                'Summarize my lab results',
                'What medications might interact?',
                'Explain this diagnosis in plain language',
              ].map((text) => (
                <button
                  key={text}
                  type="button"
                  onClick={() => orch.send(text)}
                  className="rounded-full border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-accent hover:text-accent"
                >
                  {text}
                </button>
              ))}
            </div>
          </div>
          <div className="bc-chat-anchor w-full px-4">
            {busy && orch.phase ? (
              <StreamStatusBar phase={orch.phase} startedAt={orch.startedAt} pipelineEvents={orch.pipelineEvents} />
            ) : null}
            {orch.stale && busy ? (
              <StaleStreamBanner onRetry={orch.retry} onDiscard={orch.dismiss} />
            ) : null}
            {orch.sendError ? (
              <div className={cn(
                'mb-2 flex items-center justify-center gap-2 rounded-md border px-3 py-2',
                orch.sendError.startsWith('⚠')
                  ? 'border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400'
                  : 'border-transparent text-destructive',
              )} role="alert">
                <p className="text-sm">{renderSendError(orch.sendError, resolvedWorkspaceId)}</p>
                {orch.canRetry && !orch.sendError.startsWith('⚠') ? (
                  <button
                    type="button"
                    onClick={orch.retry}
                    className="text-sm text-primary underline underline-offset-2 hover:no-underline"
                  >
                    Retry
                  </button>
                ) : null}
              </div>
            ) : null}
            <ChatInput
              inputRef={orch.inputRef}
              value={orch.draft}
              onChange={orch.setDraft}
              onSend={orch.send}
              disabled={false}
              streaming={busy}
              onStop={orch.stop}
              activeChatId={null}
              chatMaxW={chatMaxW}
              attachedSources={orch.attachedSources}
              onRemoveAttached={orch.removeAttachedSource}
            />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
      <div className="sr-only" aria-live="polite" aria-atomic="false">{ariaLiveText}</div>
      <WorkspaceTitle />
      <div className="mx-auto flex min-h-0 w-full flex-1 flex-col" style={{ maxWidth: chatMaxW, '--bc-chat-anchor-extra': `${anchorExtraPx}px` }}>
        {!busy && !isLoading && messages.length > 0 && (
          <div className="flex justify-end px-4 pb-1">
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    className="size-8 text-muted-foreground"
                    onClick={() => downloadConversation(messages, chatTitle)}
                    aria-label="Download conversation"
                  >
                    <Download className="size-3.5" />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>Download conversation</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
        )}
        <DisclaimerBanner />
        <div className="bc-chat-messages-mobile min-h-0 flex-1">
          {isLoading && !busy ? (
            <MessageListSkeleton />
          ) : (
            <MessageList
              chatId={activeChatId}
              messages={orch.displayMessages}
              streamingAssistant={orch.streamingTail}
              sourcesByMessageIndex={orch.sourcesByMessageIndex}
              streamingRagContext={busy ? orch.streamingRag : null}
              onSaveMessageAsNote={notesWorkspaceIdForSave ? saveMessageAsNote : undefined}
              onEditUser={orch.editUser}
              onRegenerate={orch.regenerate}
              pruningSummary={chat?.pruning_summary ?? null}
            />
          )}
        </div>
        <div
          className="bc-chat-anchor shrink-0 px-4"
          style={{
            // Desktop only — on mobile, .bc-chat-anchor positions via fixed +
            // bottom: max(safe-area, --bc-keyboard-pad). On desktop, this
            // padding-bottom keeps the input above the home indicator.
            paddingBottom:
              'max(0px, calc(1rem + env(safe-area-inset-bottom, 0px) - var(--bc-keyboard-pad, 0px)))',
          }}
        >
          {busy && orch.phase ? (
            <StreamStatusBar phase={orch.phase} startedAt={orch.startedAt} pipelineEvents={orch.pipelineEvents} />
          ) : null}
          {orch.stale && busy ? (
            <StaleStreamBanner onRetry={orch.retry} onDiscard={orch.dismiss} />
          ) : null}
          {orch.sendError ? (
            <div className={cn(
              'mb-2 flex items-center gap-2 rounded-md border px-3 py-2',
              orch.sendError.startsWith('⚠')
                ? 'border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400'
                : 'border-transparent text-destructive',
            )} role="alert">
              <p className="flex-1 text-sm">{renderSendError(orch.sendError, resolvedWorkspaceId)}</p>
              {orch.canRetry && !orch.sendError.startsWith('⚠') ? (
                <button
                  type="button"
                  onClick={orch.retry}
                  className="text-sm text-primary underline underline-offset-2 hover:no-underline"
                >
                  Retry
                </button>
              ) : null}
            </div>
          ) : null}
          <ChatInput
            inputRef={orch.inputRef}
            value={orch.draft}
            onChange={orch.setDraft}
            onSend={orch.send}
            disabled={false}
            streaming={busy}
            onStop={orch.stop}
            activeChatId={activeChatId}
            chatMaxW={chatMaxW}
            attachedSources={orch.attachedSources}
            onRemoveAttached={orch.removeAttachedSource}
          />
          <ContextIndicator promptTokens={promptTokens} ctxMax={ctxMax} />
        </div>
      </div>
    </div>
  )
}
