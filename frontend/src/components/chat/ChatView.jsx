import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { createChat, forkChat, getChat, listMessages, patchRecentChatsListCache } from '@/api/chats.js'
import { createNote } from '@/api/notes.js'
import { getDurableStreamingSetting } from '@/api/settings.js'
import { useDurableChat } from '@/hooks/useDurableChat.js'
import { useStream } from '@/hooks/useStream.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

import { AssistantGlyph } from './AssistantGlyph.jsx'
import { ChatInput } from './ChatInput.jsx'
import { ContextIndicator } from './ContextIndicator.jsx'
import { DisclaimerBanner } from './DisclaimerBanner.jsx'
import { MessageList } from './MessageList.jsx'
import { ModelSelectorBar } from './ModelSelectorBar.jsx'
import { StaleStreamBanner } from './StaleStreamBanner.jsx'
import { StreamStatusBar } from './StreamStatusBar.jsx'

const STALE_STREAM_MS = 60_000
const THINKING_PHASE_MS = 3_000

const KNOWN_PHASES = new Set([
  'preparing', 'loading', 'ready', 'unloading', 'rag', 'search',
  'embedding', 'searching', 'reranking', 'thinking', 'generating',
])

function mapStreamPhase(raw) {
  if (raw === 'inference') return 'thinking'
  if (KNOWN_PHASES.has(raw)) return raw
  return 'preparing'
}

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
  const s = String(msg)
  if (/load failed|network error|failed to fetch|network connection was lost/i.test(s)) {
    return (
      'Connection lost while waiting for the model. Retrieval and CPU inference can take '
      + '1–2 minutes — tap Retry and keep this tab open, or start a fresh chat.'
    )
  }
  if (s.includes('The model returned no response')) return s
  if (s.includes('Inference error')) {
    return s.length > 200 ? `${s.slice(0, 200)}…` : s
  }
  return s
}

function categoryToReason(category) {
  switch (category) {
    case 'prompt_injection': return 'it appeared to contain a prompt injection attempt'
    case 'pii_leak': return 'it may contain personally identifiable information'
    case 'medical_advice': return 'it requested specific medical advice'
    case 'crisis_content': return 'it contained crisis-related content'
    case 'hallucinated_id': return 'it referenced an unverifiable identifier'
    default: return `it was flagged for ${category}`
  }
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

  // Reconnect to an in-progress durable stream after page refresh
  const resumedRef = useRef(null)
  useEffect(() => {
    if (!durableEnabled || durable.busy || !activeChatId || !messages.length) return
    if (resumedRef.current === activeChatId) return
    const streaming = messages.find((m) => m.role === 'assistant' && m.status === 'streaming')
    if (streaming) {
      resumedRef.current = activeChatId
      durable.resume(activeChatId, streaming.id)
    }
  }, [durableEnabled, durable.busy, activeChatId, messages])

  const [draft, setDraft] = useState('')
  const [attachedSources, setAttachedSources] = useState([])

  useEffect(() => {
    function handleAttach(e) {
      const { name, id } = e.detail || {}
      if (!name || !id) return
      setAttachedSources(prev => {
        if (prev.some(s => s.id === id)) return prev
        return [...prev, { name, id }]
      })
      inputRef.current?.focus()
    }
    window.addEventListener('hlh:attach-source', handleAttach)
    return () => window.removeEventListener('hlh:attach-source', handleAttach)
  }, [])

  function removeAttachedSource(id) {
    setAttachedSources(prev => prev.filter(s => s.id !== id))
  }
  const [streamText, setStreamText] = useState('')
  const [sendError, setSendError] = useState(null)
  const [streamPhase, setStreamPhase] = useState(null)
  const [streamStartedAt, setStreamStartedAt] = useState(null)
  const [pipelineEvents, setPipelineEvents] = useState([])
  const [streamStale, setStreamStale] = useState(false)

  const { consumeStream, abort } = useStream()

  const { data: durableConfig } = useQuery({
    queryKey: ['settings', 'durable-streaming'],
    queryFn: getDurableStreamingSetting,
    staleTime: 5 * 60_000,
  })
  const durableEnabled = durableConfig?.enabled === true
  const durable = useDurableChat()

  const effectiveStop = useCallback(() => {
    if (durableEnabled && durable.busy) {
      durable.stop()
    } else {
      abort()
    }
  }, [durableEnabled, durable, abort])

  const [pendingSend, setPendingSend] = useState(false)
  const [optimisticUser, setOptimisticUser] = useState(null)
  const [sourcesByMessageIndex, setSourcesByMessageIndex] = useState({})
  const [streamingRag, setStreamingRag] = useState(null)
  const streamAssistantIndexRef = useRef(0)
  /** Chat id for the in-flight POST /messages stream (not null only while consumeStream runs). */
  const streamingChatRef = useRef(null)
  const lastStreamActivityRef = useRef(null)
  const inputRef = useRef(null)
  /** Last outgoing user message content — used to power the Retry button on stream errors. */
  const lastUserMessageRef = useRef(null)

  const busy = pendingSend

  useEffect(() => {
    if (!busy && inputRef.current) {
      inputRef.current.focus()
    }
  }, [busy])

  const serverHasPendingUserBubble =
    messages.length > 0 &&
    optimisticUser &&
    messages.some((m) => m.role === 'user' && sameUserBubbleContent(m.content, optimisticUser.content))
  const showOptimistic =
    Boolean(pendingSend && optimisticUser) && !serverHasPendingUserBubble
  const baseMessages = busy
    ? messages.filter((m) => !(m.role === 'assistant' && m.status === 'streaming'))
    : messages
  const displayMessages = showOptimistic ? [...baseMessages, optimisticUser] : baseMessages

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
      clearStreamUi()
    }
  }, [activeChatId, pendingSend, abort])

  function touchStreamActivity(nextLen) {
    lastStreamActivityRef.current = { len: nextLen, at: Date.now() }
    setStreamStale(false)
  }

  function beginStreamUi() {
    const startedAt = Date.now()
    setStreamPhase('preparing')
    setStreamStartedAt(startedAt)
    setPipelineEvents([])
    setStreamStale(false)
    touchStreamActivity(0)
  }

  function clearStreamUi() {
    setStreamPhase(null)
    setStreamStartedAt(null)
    setPipelineEvents([])
    setStreamStale(false)
    lastStreamActivityRef.current = null
  }

  useEffect(() => {
    if (!busy || streamPhase === 'generating') return undefined
    const t = window.setTimeout(() => {
      setStreamPhase((phase) => (
        phase === 'preparing' || phase === 'rag' || phase === 'search' ? 'thinking' : phase
      ))
    }, THINKING_PHASE_MS)
    return () => window.clearTimeout(t)
  }, [busy, streamPhase])

  useEffect(() => {
    if (!busy) {
      setStreamStale(false)
      return undefined
    }
    const interval = window.setInterval(() => {
      const activity = lastStreamActivityRef.current
      if (!activity) return
      if (Date.now() - activity.at >= STALE_STREAM_MS) {
        setStreamStale(true)
      }
    }, 5_000)
    return () => window.clearInterval(interval)
  }, [busy, streamText])

  // Sync durable hook state → existing ChatView UI state
  useEffect(() => {
    if (!durableEnabled) return
    if (durable.busy) {
      setPendingSend(true)
      if (durable.streamingContent) {
        setStreamText(durable.streamingContent)
        setStreamPhase('generating')
        touchStreamActivity(durable.streamingContent.length)
      } else if (streamPhase !== 'generating') {
        setStreamPhase('thinking')
      }
    } else if (pendingSend && durable.streamingStatus === null) {
      const cid = activeChatId
      if (cid) {
        listMessages(cid).then((data) => {
          if (data) queryClient.setQueryData(['messages', cid], data)
          flushSync(() => {
            setOptimisticUser(null)
            setPendingSend(false)
            setStreamText('')
            setStreamingRag(null)
            clearStreamUi()
            setSendError(null)
          })
          queryClient.invalidateQueries({ queryKey: ['chats'] })
          queryClient.invalidateQueries({ queryKey: ['chat', cid] })
        }).catch(console.error)
      }
    }
    if (durable.stale) setStreamStale(true)
    if (durable.sendError && !sendError) setSendError(friendlyStreamError(durable.sendError))
  }, [durableEnabled, durable.busy, durable.streamingContent, durable.stale, durable.sendError, durable.streamingStatus])

  async function runStream(chatId, content, assistantMessageIndex, sourceIds = null, { retryLast = false } = {}) {
    streamingChatRef.current = chatId
    streamAssistantIndexRef.current = assistantMessageIndex
    beginStreamUi()
    const model = selectedModel || undefined
    await consumeStream({
      url: `/api/chats/${chatId}/messages`,
      body: {
        content,
        retry_last: retryLast,
        ...(model ? { model } : {}),
        ...(sourceIds ? { attached_source_ids: sourceIds } : {}),
      },
      onToken: (t) => {
        setStreamPhase('generating')
        setStreamText((x) => {
          const next = x + t
          touchStreamActivity(next.length)
          return next
        })
      },
      onSearchSources: (sources) => {
        setStreamPhase('search')
        touchStreamActivity(0)
        const idx = streamAssistantIndexRef.current
        setSourcesByMessageIndex((prev) => ({ ...prev, [idx]: sources }))
      },
      onRagContext: (info) => {
        setStreamPhase('rag')
        touchStreamActivity(0)
        setStreamingRag(info)
      },
      onPhase: (raw, meta = {}) => {
        const mapped = mapStreamPhase(raw)
        setStreamPhase(mapped)
        setPipelineEvents((prev) => [...prev, {
          phase: mapped,
          model: meta.model,
          estimate_ms: meta.estimate_ms,
        }])
        touchStreamActivity(0)
      },
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
          clearStreamUi()
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
          clearStreamUi()
          if (err?.name !== 'AbortError') {
            const raw = err instanceof Error ? err.message : String(err)
            try {
              const parsed = JSON.parse(raw)
              if (parsed.error === 'input_blocked') {
                const category = parsed.guard_flags?.[0]?.category || 'safety policy'
                const reason = categoryToReason(category)
                setSendError(`⚠ This message was blocked because ${reason}. You can rephrase as an educational question.`)
                setDraft(lastUserMessageRef.current || '')
              } else {
                setSendError(friendlyStreamError(raw))
              }
            } catch {
              setSendError(friendlyStreamError(raw))
            }
          }
        })
        queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
      },
    })
  }

  async function send(contentOverride) {
    const rawContent = (typeof contentOverride === 'string' ? contentOverride : draft).trim()
    if (!rawContent || busy) return
    let content = rawContent
    const sourceIds = attachedSources.length > 0 ? attachedSources.map(s => s.id) : null
    if (sourceIds) {
      const names = attachedSources.map(s => s.name).join(', ')
      content = rawContent + `\n\n📎 ${names}`
    }
    lastUserMessageRef.current = content
    setDraft('')
    setAttachedSources([])
    setSendError(null)

    // --- Durable streaming path ---
    if (durableEnabled) {
      setPendingSend(true)
      beginStreamUi()
      setStreamText('')
      setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })

      let targetChatId = activeChatId
      if (!targetChatId) {
        try {
          const { activeWorkspaceId } = useAppStore.getState()
          const workspaceForCreate =
            normalizeWorkspaceUuid(activeWorkspaceId) || resolvedWorkspaceId || undefined
          const modelForCreate = selectedModel || undefined
          const newChat = await createChat({
            ...(modelForCreate ? { model: modelForCreate } : {}),
            ...(workspaceForCreate ? { workspace_id: workspaceForCreate } : {}),
            ...(webSearchEnabled ? { web_search_enabled: true } : {}),
          })
          if (newChat?.id == null) throw new Error('Create chat returned no id')
          queryClient.setQueryData(['messages', newChat.id], { items: [] })
          setActiveChatId(newChat.id)
          hydrateFromChat(newChat)
          queryClient.invalidateQueries({ queryKey: ['chats'] })
          targetChatId = newChat.id
        } catch (e) {
          console.error(e)
          setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
          setOptimisticUser(null)
          setPendingSend(false)
          setStreamText('')
          clearStreamUi()
          setDraft(content)
          setActiveChatId(null)
          return
        }
      }

      try {
        await durable.sendMessage(targetChatId, content, {
          model: selectedModel || undefined,
          attachedSourceIds: sourceIds,
        })
      } catch (e) {
        console.error(e)
        setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
        clearStreamUi()
        setDraft(content)
      }
      return
    }

    if (!activeChatId) {
      setPendingSend(true)
      beginStreamUi()
      setStreamText('')
      setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
      try {
        const { activeWorkspaceId } = useAppStore.getState()
        const workspaceForCreate =
          normalizeWorkspaceUuid(activeWorkspaceId) || resolvedWorkspaceId || undefined
        const modelForCreate = selectedModel || undefined
        const newChat = await createChat({
          ...(modelForCreate ? { model: modelForCreate } : {}),
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
        await runStream(newChat.id, content, messages.length + 1, sourceIds)
      } catch (e) {
        console.error(e)
        setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
        clearStreamUi()
        setDraft(content)
        setActiveChatId(null)
        streamingChatRef.current = null
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
      }
      return
    }

    setPendingSend(true)
    beginStreamUi()
    setStreamText('')
    setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
    await runStream(activeChatId, content, messages.length + 1, sourceIds)
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
      beginStreamUi()
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
    if (!last || busy || !activeChatId) return
    effectiveStop()
    setSendError(null)
    setStreamStale(false)
    if (durableEnabled) {
      setPendingSend(true)
      beginStreamUi()
      setStreamText('')
      setOptimisticUser(null)
      durable.sendMessage(activeChatId, last, {
        retryLast: true,
        model: selectedModel || undefined,
      }).catch((e) => {
        console.error(e)
        setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
        setPendingSend(false)
        clearStreamUi()
      })
      return
    }
    setPendingSend(true)
    beginStreamUi()
    setStreamText('')
    const lastMsg = messages[messages.length - 1]
    const skipOptimistic = lastMsg?.role === 'user' && sameUserBubbleContent(lastMsg.content, last)
    setOptimisticUser(skipOptimistic ? null : { id: '__optimistic_user__', role: 'user', content: last })
    void runStream(activeChatId, last, messages.length, null, { retryLast: true })
  }

  function dismissStaleStream() {
    if (durableEnabled) {
      durable.discardStale()
    } else {
      abort()
    }
    clearStreamUi()
    setPendingSend(false)
    setStreamText('')
    setOptimisticUser(null)
    if (activeChatId) {
      queryClient.invalidateQueries({ queryKey: ['messages', activeChatId] })
    }
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

  const latestAssistant = [...(messages || [])].reverse().find(m => m.role === 'assistant' && m.prompt_tokens)
  const promptTokens = latestAssistant?.prompt_tokens
  const ctxMax = chat?.ctx_max

  // While the status bar shows prefill/thinking, skip the duplicate pending assistant bubble.
  const streamingTail = busy
    ? (streamText !== '' ? streamText : (streamPhase ? null : ''))
    : null

  const anchorExtraPx =
    (busy && streamPhase ? 52 : 0)
    + (streamStale && busy ? 56 : 0)
    + (sendError ? 44 : 0)

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
            <AssistantGlyph kind="header" />
            <h1 className="fs-heading text-center font-semibold tracking-tight text-foreground">Assistant</h1>
          </div>
          <div className="bc-chat-anchor w-full px-4">
            {busy && streamPhase ? (
              <StreamStatusBar phase={streamPhase} startedAt={streamStartedAt} pipelineEvents={pipelineEvents} />
            ) : null}
            {streamStale && busy ? (
              <StaleStreamBanner onRetry={retryLastSend} onDiscard={dismissStaleStream} />
            ) : null}
            {sendError ? (
              <div className={cn(
                'mb-2 flex items-center justify-center gap-2 rounded-md border px-3 py-2',
                sendError.startsWith('⚠')
                  ? 'border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400'
                  : 'border-transparent text-destructive',
              )} role="alert">
                <p className="text-sm">{sendError}</p>
                {lastUserMessageRef.current && !sendError.startsWith('⚠') ? (
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
              onStop={effectiveStop}
              activeChatId={null}
              chatMaxW={chatMaxW}
              attachedSources={attachedSources}
              onRemoveAttached={removeAttachedSource}
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
      <div className="mx-auto flex min-h-0 w-full flex-1 flex-col" style={{ maxWidth: chatMaxW, '--bc-chat-anchor-extra': `${anchorExtraPx}px` }}>
        <DisclaimerBanner />
        <div className="bc-chat-messages-mobile min-h-0 flex-1">
          {isLoading && !busy ? (
            <MessageListSkeleton />
          ) : (
            <MessageList
              chatId={activeChatId}
              messages={displayMessages}
              streamingAssistant={streamingTail}
              sourcesByMessageIndex={sourcesByMessageIndex}
              streamingRagContext={busy ? streamingRag : null}
              onSaveMessageAsNote={notesWorkspaceIdForSave ? saveMessageAsNote : undefined}
              onEditUser={handleEditUser}
              onRegenerate={handleRegenerate}
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
          {busy && streamPhase ? (
            <StreamStatusBar phase={streamPhase} startedAt={streamStartedAt} pipelineEvents={pipelineEvents} />
          ) : null}
          {streamStale && busy ? (
            <StaleStreamBanner onRetry={retryLastSend} onDiscard={dismissStaleStream} />
          ) : null}
          {sendError ? (
            <div className={cn(
              'mb-2 flex items-center gap-2 rounded-md border px-3 py-2',
              sendError.startsWith('⚠')
                ? 'border-yellow-500/30 bg-yellow-500/5 text-yellow-700 dark:text-yellow-400'
                : 'border-transparent text-destructive',
            )} role="alert">
              <p className="flex-1 text-sm">{sendError}</p>
              {lastUserMessageRef.current && !sendError.startsWith('⚠') ? (
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
            onStop={effectiveStop}
            activeChatId={activeChatId}
            chatMaxW={chatMaxW}
            attachedSources={attachedSources}
            onRemoveAttached={removeAttachedSource}
          />
          <ContextIndicator promptTokens={promptTokens} ctxMax={ctxMax} />
        </div>
      </div>
    </div>
  )
}
