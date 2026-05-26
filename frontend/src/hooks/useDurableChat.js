import { useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiFetch } from '@/api/index.js'
import { listMessages, stopChatInference, discardStaleMessage } from '@/api/chats.js'

const POLL_FAST_MS = 1000
const POLL_MEDIUM_MS = 2000
const POLL_SLOW_MS = 5000
const POLL_FAST_DURATION_MS = 10_000
const POLL_MEDIUM_DURATION_MS = 30_000
const STALE_THRESHOLD_MS = 60_000

export function useDurableChat() {
  const queryClient = useQueryClient()
  const [streamingMessageId, setStreamingMessageId] = useState(null)
  const [streamingContent, setStreamingContent] = useState('')
  const [streamingStatus, setStreamingStatus] = useState(null)
  const [sendError, setSendError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [stale, setStale] = useState(false)

  const pollRef = useRef(null)
  const sendTimeRef = useRef(null)
  const lastContentLenRef = useRef(0)
  const lastContentChangeRef = useRef(null)
  const chatIdRef = useRef(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearTimeout(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const getPollInterval = useCallback(() => {
    if (!sendTimeRef.current) return POLL_MEDIUM_MS
    const elapsed = Date.now() - sendTimeRef.current
    if (elapsed < POLL_FAST_DURATION_MS) return POLL_FAST_MS
    if (elapsed < POLL_MEDIUM_DURATION_MS) return POLL_MEDIUM_MS
    return POLL_SLOW_MS
  }, [])

  const pollOnce = useCallback(async (chatId, assistantMsgId) => {
    try {
      const data = await listMessages(chatId)
      const items = data?.items ?? []
      queryClient.setQueryData(['messages', chatId], data)

      const target = items.find((m) => m.id === assistantMsgId)
      if (!target) return

      const content = target.content || ''
      setStreamingContent(content)

      if (content.length !== lastContentLenRef.current) {
        lastContentLenRef.current = content.length
        lastContentChangeRef.current = Date.now()
        setStale(false)
      } else if (
        lastContentChangeRef.current &&
        Date.now() - lastContentChangeRef.current >= STALE_THRESHOLD_MS
      ) {
        setStale(true)
      }

      if (target.status === 'complete') {
        setStreamingMessageId(null)
        setStreamingContent('')
        setStreamingStatus(null)
        setBusy(false)
        setStale(false)
        stopPolling()
        queryClient.invalidateQueries({ queryKey: ['chats'] })
        queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
        return
      }

      if (target.status === 'failed' || target.status === 'cancelled') {
        setStreamingMessageId(null)
        setStreamingContent('')
        setStreamingStatus(target.status)
        setBusy(false)
        setStale(false)
        stopPolling()
        if (target.status === 'failed') {
          setSendError(target.error_message || 'Inference failed.')
        }
        return
      }

      const interval = getPollInterval()
      pollRef.current = setTimeout(() => pollOnce(chatId, assistantMsgId), interval)
    } catch (err) {
      console.error('poll failed', err)
      const interval = getPollInterval()
      pollRef.current = setTimeout(() => pollOnce(chatId, assistantMsgId), interval)
    }
  }, [queryClient, stopPolling, getPollInterval])

  const sendMessage = useCallback(async (chatId, content, { retryLast = false, model, attachedSourceIds } = {}) => {
    setSendError(null)
    setBusy(true)
    setStale(false)
    sendTimeRef.current = Date.now()
    lastContentLenRef.current = 0
    lastContentChangeRef.current = Date.now()
    chatIdRef.current = chatId

    try {
      const res = await apiFetch(`/api/chats/${chatId}/messages`, {
        method: 'POST',
        json: {
          content,
          retry_last: retryLast,
          ...(model ? { model } : {}),
          ...(attachedSourceIds ? { attached_source_ids: attachedSourceIds } : {}),
        },
      })

      if (res?.status === 'streaming' && res.assistant_message_id) {
        setStreamingMessageId(res.assistant_message_id)
        setStreamingStatus('streaming')
        pollRef.current = setTimeout(
          () => pollOnce(chatId, res.assistant_message_id),
          POLL_FAST_MS,
        )
        return res
      }

      setBusy(false)
      return res
    } catch (err) {
      setBusy(false)
      setSendError(err instanceof Error ? err.message : String(err))
      throw err
    }
  }, [pollOnce])

  const stop = useCallback(async () => {
    const chatId = chatIdRef.current
    if (!chatId) return
    stopPolling()
    try {
      await stopChatInference(chatId)
    } catch (err) {
      console.error('stop failed', err)
    }
    setStreamingMessageId(null)
    setStreamingContent('')
    setStreamingStatus(null)
    setBusy(false)
    setStale(false)
    if (chatId) {
      queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
    }
  }, [stopPolling, queryClient])

  const discardStale = useCallback(async () => {
    const chatId = chatIdRef.current
    const msgId = streamingMessageId
    if (!chatId || !msgId) return
    stopPolling()
    try {
      await discardStaleMessage(chatId, msgId)
    } catch (err) {
      console.error('discard-stale failed', err)
    }
    setStreamingMessageId(null)
    setStreamingContent('')
    setStreamingStatus(null)
    setBusy(false)
    setStale(false)
    if (chatId) {
      queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
    }
  }, [streamingMessageId, stopPolling, queryClient])

  useEffect(() => {
    function handleVisibilityChange() {
      if (document.visibilityState === 'visible' && streamingMessageId && chatIdRef.current) {
        pollOnce(chatIdRef.current, streamingMessageId)
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [streamingMessageId, pollOnce])

  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  return {
    sendMessage,
    stop,
    discardStale,
    streamingMessageId,
    streamingContent,
    streamingStatus,
    sendError,
    setSendError,
    busy,
    stale,
  }
}
