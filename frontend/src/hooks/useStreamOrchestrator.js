import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'

import { createChat, forkChat, listMessages, patchRecentChatsListCache } from '@/api/chats.js'
import { useDurableChat } from '@/hooks/useDurableChat.js'
import { useStream } from '@/hooks/useStream.js'
import { useAppStore } from '@/store/index.js'

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

function normalizeWorkspaceUuid(raw) {
  if (raw == null || raw === '') return null
  const s = String(raw).trim()
  return WORKSPACE_UUID_RE.test(s) ? s : null
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

/**
 * Streaming orchestrator. Owns BOTH streaming protocols behind a single interface:
 * an SSE branch (push: `useStream` → `consumeStream`/`runStream`) and a durable
 * branch (pull: `useDurableChat` polling, mirrored into the same local state by the
 * durable-sync effect). The two internal branches are intentionally kept separate —
 * collapsing them is deferred. ChatView consumes the unified return value and renders.
 *
 * Inputs come from ChatView's context (queries + store selectors) so the hook stays
 * reactive exactly as the in-component code did:
 *   { durableEnabled, activeChatId, setActiveChatId, messages, selectedModel,
 *     webSearchEnabled, resolvedWorkspaceId, hydrateFromChat }
 */
export function useStreamOrchestrator({
  durableEnabled,
  activeChatId,
  setActiveChatId,
  messages,
  selectedModel,
  webSearchEnabled,
  resolvedWorkspaceId,
  hydrateFromChat,
}) {
  const queryClient = useQueryClient()
  const durable = useDurableChat()

  // Reconnect to an in-progress durable stream after page refresh
  const resumedRef = useRef(null)

  // Reset resume state when switching chats so the new chat can reconnect.
  // Stops any in-progress stream from the previous chat before switching.
  useEffect(() => {
    resumedRef.current = null
    if (durable.busy) durable.stop() // eslint-disable-line react-hooks/exhaustive-deps
  }, [activeChatId]) // intentionally omits durable to avoid infinite loop

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
  const [streamWarnings, setStreamWarnings] = useState([])
  const [streamStale, setStreamStale] = useState(false)

  const { consumeStream, abort } = useStream()

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
  /** Chat ID resolved when the durable send path starts — used for cleanup even if user switches chats mid-stream. */
  const durableInitChatRef = useRef(null)

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
    ? messages.filter((m) => {
        if (m.role !== 'assistant') return true
        if (m.status === 'streaming') return false
        if (durableEnabled && durable.streamingMessageId && m.id === durable.streamingMessageId) return false
        return true
      })
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
    setStreamWarnings([])
    setStreamStale(false)
    touchStreamActivity(0)
  }

  function clearStreamUi({ keepWarnings = false } = {}) {
    setStreamPhase(null)
    setStreamStartedAt(null)
    setPipelineEvents([])
    if (!keepWarnings) setStreamWarnings([])
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

  // Stale-stream watcher. Reads `lastStreamActivityRef` (a ref, updated on every token by
  // touchStreamActivity), so `streamText` must NOT be a dependency — including it tore the
  // interval down and rebuilt it on every streamed token, resetting the 5s tick cadence.
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
  }, [busy])

  // Sync durable hook state → existing ChatView UI state.
  // `streamPhase` is a dependency: the body reads it (the `streamPhase !== 'generating'`
  // guard) and without it the effect closed over a stale value and could miss the
  // thinking→generating transition.
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
      const cid = durableInitChatRef.current || activeChatId
      if (cid) {
        durableInitChatRef.current = null
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
  }, [durableEnabled, durable.busy, durable.streamingContent, durable.stale, durable.sendError, durable.streamingStatus, streamPhase])

  function beginStream(content) {
    setPendingSend(true)
    beginStreamUi()
    setStreamText('')
    setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
  }

  async function createChatIfNeeded() {
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
    return newChat.id
  }

  function handleStreamError(e, content) {
    console.error(e)
    setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
    setOptimisticUser(null)
    setPendingSend(false)
    setStreamText('')
    clearStreamUi()
    setDraft(content)
  }

  function makeOnToken() {
    return (t) => {
      setStreamPhase('generating')
      setStreamText((x) => {
        const next = x + t
        touchStreamActivity(next.length)
        return next
      })
    }
  }

  function makeOnSearchSources() {
    return (sources) => {
      setStreamPhase('search')
      touchStreamActivity(0)
      const idx = streamAssistantIndexRef.current
      setSourcesByMessageIndex((prev) => ({ ...prev, [idx]: sources }))
    }
  }

  function makeOnRagContext() {
    return (info) => {
      setStreamPhase('rag')
      touchStreamActivity(0)
      setStreamingRag(info)
    }
  }

  function makeOnWarning() {
    return (message) => {
      if (!message) return
      setStreamWarnings((prev) => [...prev, String(message)])
    }
  }

  function makeOnPhase() {
    return (raw, meta = {}) => {
      const mapped = mapStreamPhase(raw)
      setStreamPhase(mapped)
      setPipelineEvents((prev) => [...prev, {
        phase: mapped,
        model: meta.model,
        estimate_ms: meta.estimate_ms,
      }])
      touchStreamActivity(0)
    }
  }

  function makeOnTitleUpdate(chatId) {
    return (title) => {
      patchRecentChatsListCache(queryClient, chatId, title)
      queryClient.setQueryData(['chat', chatId], (old) => (old ? { ...old, title } : old))
      queryClient.invalidateQueries({ queryKey: ['chats'] })
    }
  }

  function makeOnDone(chatId) {
    return async () => {
      streamingChatRef.current = null
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
        clearStreamUi({ keepWarnings: true })
      })
      if (!nextData) {
        queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
      }
      queryClient.invalidateQueries({ queryKey: ['chats'] })
      queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
    }
  }

  function makeOnError(chatId) {
    return async (err) => {
      streamingChatRef.current = null
      flushSync(() => {
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
        setStreamingRag(null)
        clearStreamUi({ keepWarnings: true })
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
    }
  }

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
      onToken: makeOnToken(),
      onSearchSources: makeOnSearchSources(),
      onRagContext: makeOnRagContext(),
      onPhase: makeOnPhase(),
      onTitleUpdate: makeOnTitleUpdate(chatId),
      onWarning: makeOnWarning(),
      onDone: makeOnDone(chatId),
      onError: makeOnError(chatId),
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

    if (durableEnabled) {
      beginStream(content)

      let targetChatId = activeChatId
      if (!targetChatId) {
        try {
          targetChatId = await createChatIfNeeded()
        } catch (e) {
          handleStreamError(e, content)
          setActiveChatId(null)
          return
        }
      }

      durableInitChatRef.current = targetChatId

      try {
        await durable.sendMessage(targetChatId, content, {
          model: selectedModel || undefined,
          attachedSourceIds: sourceIds,
        })
      } catch (e) {
        handleStreamError(e, content)
      }
      return
    }

    if (!activeChatId) {
      beginStream(content)
      try {
        const chatId = await createChatIfNeeded()
        streamingChatRef.current = chatId
        await runStream(chatId, content, messages.length + 1, sourceIds)
      } catch (e) {
        handleStreamError(e, content)
        setActiveChatId(null)
        streamingChatRef.current = null
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
      }
      return
    }

    beginStream(content)
    try {
      await runStream(activeChatId, content, messages.length + 1, sourceIds)
    } catch (e) {
      handleStreamError(e, content)
    }
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
      clearStreamUi()
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
    try {
      void runStream(activeChatId, last, messages.length, null, { retryLast: true })
    } catch (e) {
      console.error(e)
      setPendingSend(false)
      setStreamText('')
      setOptimisticUser(null)
      clearStreamUi()
      setSendError(friendlyStreamError(e instanceof Error ? e.message : String(e)))
    }
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

  // While the status bar shows prefill/thinking, skip the duplicate pending assistant bubble.
  const streamingTail = busy
    ? (streamText !== '' ? streamText : (streamPhase ? null : ''))
    : null

  return {
    text: streamText,
    phase: streamPhase,
    busy,
    stale: streamStale,
    sendError,
    send,
    stop: effectiveStop,
    retry: retryLastSend,
    forkAndStream,
    editUser: handleEditUser,
    regenerate: handleRegenerate,
    dismiss: dismissStaleStream,
    optimisticUser,
    serverHasPendingMessage: serverHasPendingUserBubble,
    displayMessages,
    startedAt: streamStartedAt,
    pipelineEvents,
    streamWarnings,
    sourcesByMessageIndex,
    streamingRag,
    streamingTail,
    canRetry: Boolean(lastUserMessageRef.current),
    draft,
    setDraft,
    attachedSources,
    removeAttachedSource,
    inputRef,
  }
}
