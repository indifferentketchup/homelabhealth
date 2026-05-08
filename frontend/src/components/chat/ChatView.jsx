import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { createChat, forkChat, getChat, listMessages, patchRecentChatsListCache } from '@/api/chats.js'
import { createNote } from '@/api/notes.js'
import { useStream } from '@/hooks/useStream.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

import { PersonaMark } from './PersonaMark.jsx'
import { ChatInput } from './ChatInput.jsx'
import { MessageList } from './MessageList.jsx'
import { ModelSelectorBar } from './ModelSelectorBar.jsx'

function sameUserBubbleContent(serverText, optimisticText) {
  return String(serverText ?? '').trim() === String(optimisticText ?? '').trim()
}

const WORKSPACE_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

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

function friendlyStreamError(msg) {
  if (!msg) return 'Something went wrong.'
  return String(msg)
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
  const personaDisplayName = useAppStore((s) => s.personaDisplayName)
  const personaIconUrl = useAppStore((s) => s.personaIconUrl)
  const personaEmoji = useAppStore((s) => s.personaEmoji)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const setChats = useAppStore((s) => s.setChats)

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
  const [draft, setDraft] = useState('')
  const [streamText, setStreamText] = useState('')
  const [sendError, setSendError] = useState(null)

  const { consumeStream, abort } = useStream()
  const [pendingSend, setPendingSend] = useState(false)
  const [optimisticUser, setOptimisticUser] = useState(null)
  const [sourcesByMessageIndex, setSourcesByMessageIndex] = useState({})
  const [streamingRag, setStreamingRag] = useState(null)
  const streamAssistantIndexRef = useRef(0)
  /** Chat id for the in-flight POST /messages stream (not null only while consumeStream runs). */
  const streamingChatRef = useRef(null)
  const inputRef = useRef(null)
  /** Last outgoing user message content — used to power the Retry button on stream errors. */
  const lastUserMessageRef = useRef(null)

  const busy = pendingSend

  useEffect(() => {
    if (!busy && inputRef.current) {
      inputRef.current.focus()
    }
  }, [busy])

  // Avoid double user bubbles: new-chat flow enables the messages query as the stream runs, so the
  // server copy of the user message can appear in `messages` while `optimisticUser` is still set.
  const serverHasPendingUserBubble =
    messages.length > 0 &&
    messages[messages.length - 1]?.role === 'user' &&
    sameUserBubbleContent(messages[messages.length - 1]?.content, optimisticUser?.content)
  const showOptimistic =
    Boolean(pendingSend && optimisticUser) && !serverHasPendingUserBubble
  const displayMessages = showOptimistic ? [...messages, optimisticUser] : messages

  useEffect(() => {
    if (!pendingSend || !optimisticUser) return
    if (!serverHasPendingUserBubble) return
    setOptimisticUser(null)
  }, [pendingSend, optimisticUser, serverHasPendingUserBubble])

  useEffect(() => {
    setSourcesByMessageIndex({})
    setStreamingRag(null)
  }, [activeChatId])

  // Drop streaming UI when leaving the chat being streamed (abort + reset), and clear any leaked
  // stream buffer when switching threads while idle (prevents doubling the last assistant bubble).
  useEffect(() => {
    if (!pendingSend) {
      setStreamText('')
      return
    }
    const sid = streamingChatRef.current
    if (sid == null) return
    if (String(activeChatId ?? '') !== String(sid)) {
      abort()
      streamingChatRef.current = null
      setOptimisticUser(null)
      setPendingSend(false)
      setStreamText('')
    }
  }, [activeChatId, pendingSend, abort])

  async function runStream(chatId, content, assistantMessageIndex) {
    streamingChatRef.current = chatId
    streamAssistantIndexRef.current = assistantMessageIndex
    const model = selectedModel || undefined
    await consumeStream({
      url: `/api/chats/${chatId}/messages`,
      body: {
        content,
        ...(model ? { model } : {}),
      },
      onToken: (t) => setStreamText((x) => x + t),
      onSearchSources: (sources) => {
        const idx = streamAssistantIndexRef.current
        setSourcesByMessageIndex((prev) => ({ ...prev, [idx]: sources }))
      },
      onRagContext: (info) => setStreamingRag(info),
      onTitleUpdate: (title) => {
        const id = String(chatId)
        setChats(
          useAppStore.getState().chats.map((c) => (String(c.id) === id ? { ...c, title } : c)),
        )
        patchRecentChatsListCache(queryClient, chatId, title)
        queryClient.setQueryData(['chat', chatId], (old) => (old ? { ...old, title } : old))
        queryClient.invalidateQueries({ queryKey: ['chats'] })
      },
      onDone: async () => {
        streamingChatRef.current = null
        // Fetch new messages as a value so we can commit the data write and the stream
        // teardown in one render. Going via refetchQueries leaves a frame where the new
        // messages are already in RQ's store but pendingSend/streamText/optimisticUser
        // haven't cleared yet — that frame is the double-render.
        let nextData = null
        try {
          nextData = await listMessages(chatId)
        } catch (e) {
          console.error('onDone listMessages failed', e)
        }
        flushSync(() => {
          if (nextData) queryClient.setQueryData(['messages', chatId], nextData)
          setOptimisticUser(null)
          setPendingSend(false)
          setStreamingRag(null)
          setStreamText('')
          setSendError(null)
        })
        if (!nextData) {
          queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
        }
        queryClient.invalidateQueries({ queryKey: ['chats'] })
        queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
      },
      onError: async (err) => {
        streamingChatRef.current = null
        flushSync(() => {
          setOptimisticUser(null)
          setPendingSend(false)
          setStreamText('')
          setStreamingRag(null)
          if (err?.name !== 'AbortError') {
            const raw = err instanceof Error ? err.message : String(err)
            setSendError(friendlyStreamError(raw))
          }
        })
        queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
      },
    })
  }

  async function send(contentOverride) {
    const content = (typeof contentOverride === 'string' ? contentOverride : draft).trim()
    if (!content || busy) return
    lastUserMessageRef.current = content
    setDraft('')
    setSendError(null)

    if (!activeChatId) {
      setPendingSend(true)
      setStreamText('')
      setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
      try {
        const { activePersonaId, activeWorkspaceId } = useAppStore.getState()
        const workspaceForCreate =
          normalizeWorkspaceUuid(activeWorkspaceId) || resolvedWorkspaceId || undefined
        const modelForCreate = selectedModel || undefined
        const newChat = await createChat({
          ...(modelForCreate ? { model: modelForCreate } : {}),
          ...(activePersonaId ? { persona_id: activePersonaId } : {}),
          ...(workspaceForCreate ? { workspace_id: workspaceForCreate } : {}),
          ...(webSearchEnabled ? { web_search_enabled: true } : {}),
        })
        if (newChat?.id == null) {
          throw new Error('Create chat returned no id')
        }
        queryClient.setQueryData(['messages', newChat.id], { items: [] })
        setActiveChatId(newChat.id)
        streamingChatRef.current = newChat.id
        hydrateFromChat(newChat)
        queryClient.invalidateQueries({ queryKey: ['chats'] })
        await runStream(newChat.id, content, messages.length + 1)
      } catch (e) {
        console.error(e)
        setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
        setDraft(content)
        setActiveChatId(null)
        streamingChatRef.current = null
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
      }
      return
    }

    setPendingSend(true)
    setStreamText('')
    setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
    await runStream(activeChatId, content, messages.length + 1)
  }

  // Edit + regenerate both fork the current chat at a chosen message — fork creates a new chat
  // truncated to messages *before* the target — then we re-stream the new user content into it.
  async function forkAndStream(targetMessageId, newContent) {
    if (!activeChatId) return
    try {
      setSendError(null)
      const newChat = await forkChat(activeChatId, targetMessageId)
      if (!newChat?.id) throw new Error('Fork returned no chat id')
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
      queryClient.setQueryData(['messages', newChat.id], { items: [] })
      setActiveChatId(newChat.id)
      hydrateFromChat(newChat)
      setPendingSend(true)
      setStreamText('')
      setOptimisticUser({ id: '__optimistic_user__', role: 'user', content: newContent })
      await runStream(newChat.id, newContent, 1)
    } catch (e) {
      console.error(e)
      setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
      setPendingSend(false)
      setOptimisticUser(null)
      setStreamText('')
    }
  }

  function retryLastSend() {
    const last = lastUserMessageRef.current
    if (!last || busy) return
    void send(last)
  }

  async function handleEditUser(message, newContent) {
    if (!message?.id || busy) return
    await forkAndStream(message.id, newContent)
  }

  async function handleRegenerate(assistantMessage) {
    if (!assistantMessage?.id || busy) return
    const idx = messages.findIndex((m) => m.id === assistantMessage.id)
    if (idx <= 0) return
    let prevUser = null
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === 'user') {
        prevUser = messages[i]
        break
      }
    }
    if (!prevUser?.id || !prevUser.content) return
    await forkAndStream(prevUser.id, prevUser.content)
  }

  if (!activeChatId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background">
        <div className="hidden shrink-0 justify-center border-b border-border py-2 md:flex">
          <ModelSelectorBar />
        </div>
        <div
          className="flex min-h-0 flex-1 flex-col overflow-y-auto items-center justify-center gap-8 px-4 py-8 pt-[20vh] md:pt-0"
          style={{
            paddingBottom:
              'max(0px, calc(120px + max(env(safe-area-inset-bottom, 0px), var(--bc-keyboard-pad, 0px))))',
          }}
        >
          <div className="flex w-full flex-col items-center gap-4" style={{ maxWidth: chatMaxW }}>
            <PersonaMark
              iconUrl={personaIconUrl}
              emoji={personaEmoji}
              fallbackLetter={personaDisplayName?.slice(0, 1) || 'A'}
            />
            <h1 className="fs-heading text-center font-semibold tracking-tight text-foreground">{personaDisplayName}</h1>
          </div>
          <div className="bc-chat-anchor w-full px-4">
            {sendError ? (
              <div className="mb-2 flex items-center justify-center gap-2" role="alert">
                <p className="text-sm text-destructive">{sendError}</p>
                {lastUserMessageRef.current ? (
                  <button
                    type="button"
                    onClick={retryLastSend}
                    className="text-sm text-primary underline underline-offset-2 hover:no-underline"
                  >
                    Retry
                  </button>
                ) : null}
              </div>
            ) : null}
            <ChatInput
              inputRef={inputRef}
              value={draft}
              onChange={setDraft}
              onSend={send}
              disabled={false}
              streaming={busy}
              onStop={abort}
              activeChatId={null}
              chatMaxW={chatMaxW}
            />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
      <div className="hidden shrink-0 justify-center border-b border-border py-2 md:flex">
        <ModelSelectorBar />
      </div>
      <div className="mx-auto flex min-h-0 w-full flex-1 flex-col" style={{ maxWidth: chatMaxW }}>
        <div className="bc-chat-messages-mobile min-h-0 flex-1">
          {isLoading && !busy ? (
            <MessageListSkeleton />
          ) : (
            <MessageList
              chatId={activeChatId}
              messages={displayMessages}
              streamingAssistant={busy ? streamText : null}
              sourcesByMessageIndex={sourcesByMessageIndex}
              streamingRagContext={busy ? streamingRag : null}
              onSaveMessageAsNote={notesWorkspaceIdForSave ? saveMessageAsNote : undefined}
              onEditUser={handleEditUser}
              onRegenerate={handleRegenerate}
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
          {sendError ? (
            <div className="mb-2 flex items-center gap-2" role="alert">
              <p className="flex-1 text-sm text-destructive">{sendError}</p>
              {lastUserMessageRef.current ? (
                <button
                  type="button"
                  onClick={retryLastSend}
                  className="text-sm text-primary underline underline-offset-2 hover:no-underline"
                >
                  Retry
                </button>
              ) : null}
            </div>
          ) : null}
          <ChatInput
            inputRef={inputRef}
            value={draft}
            onChange={setDraft}
            onSend={send}
            disabled={false}
            streaming={busy}
            onStop={abort}
            activeChatId={activeChatId}
            chatMaxW={chatMaxW}
          />
        </div>
      </div>
    </div>
  )
}
