import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchBranding } from '@/api/branding.js'
import { createChat, getChat, listMessages, patchChat, patchRecentChatsListCache } from '@/api/chats.js'
import { useStream } from '@/hooks/useStream.js'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'

import { BooOpsMark } from './BooOpsMark.jsx'
import { ChatInput } from './ChatInput.jsx'
import { MessageList } from './MessageList.jsx'
import { ModelSelectorBar } from './ModelSelectorBar.jsx'

function sameUserBubbleContent(serverText, optimisticText) {
  return String(serverText ?? '').trim() === String(optimisticText ?? '').trim()
}

export function ChatView({
  chatMode = 'booops',
  compactEmptyState = false,
  modelBarProps = {},
  hidePersonaInChatInput = false,
}) {
  const queryClient = useQueryClient()
  const storeBranding = useAppStore((s) => s.branding)
  const { data: branding } = useQuery({
    queryKey: ['branding', chatMode],
    queryFn: () => fetchBranding(chatMode),
    staleTime: 60_000,
  })
  const chatMaxW = storeBranding?.chatMaxWidth ?? branding?.chatMaxWidth ?? 1200
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

  const { data: msgPack, isLoading } = useQuery({
    queryKey: ['messages', activeChatId],
    queryFn: () => listMessages(activeChatId),
    enabled: Boolean(activeChatId),
  })

  const messages = msgPack?.items ?? []
  const [draft, setDraft] = useState('')
  const [streamText, setStreamText] = useState('')
  const { consumeStream, abort } = useStream()
  const [pendingSend, setPendingSend] = useState(false)
  const [optimisticUser, setOptimisticUser] = useState(null)
  const [sourcesByMessageIndex, setSourcesByMessageIndex] = useState({})
  const streamAssistantIndexRef = useRef(0)
  /** Chat id for the in-flight POST /messages stream (not null only while consumeStream runs). */
  const streamingChatRef = useRef(null)

  const busy = pendingSend

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
        await queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
        await queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
      },
      onError: async () => {
        streamingChatRef.current = null
        await queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
      },
    })
  }

  async function send() {
    const content = draft.trim()
    if (!content || busy) return

    if (!activeChatId) {
      setDraft('')
      setPendingSend(true)
      setStreamText('')
      setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
      try {
        const { activePersonaId, activeDawId } = useAppStore.getState()
        const modelForCreate = selectedModel || undefined
        const newChat = await createChat({
          mode: chatMode,
          ...(modelForCreate ? { model: modelForCreate } : {}),
          ...(activePersonaId ? { persona_id: activePersonaId } : {}),
          ...(activeDawId ? { daw_id: activeDawId } : {}),
        })
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
        queryClient.setQueryData(['messages', newChat.id], { items: [] })
        setActiveChatId(newChat.id)
        hydrateFromChat(newChat)
        if (webSearchEnabled) await patchChat(newChat.id, { web_search_enabled: true })
        await runStream(newChat.id, content, messages.length + 1)
      } catch {
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
        setDraft(content)
        setActiveChatId(null)
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
      }
      return
    }

    setDraft('')
    setPendingSend(true)
    setStreamText('')
    setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
    await runStream(activeChatId, content, messages.length + 1)
  }

  if (!activeChatId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background">
        <div className="hidden shrink-0 justify-center border-b border-border py-2 md:flex">
          <ModelSelectorBar {...modelBarProps} />
        </div>
        <div
          className={cn(
            'flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-8',
            compactEmptyState ? 'justify-end' : 'items-center justify-center gap-8',
          )}
        >
          {!compactEmptyState && (
            <div className="flex w-full flex-col items-center gap-4" style={{ maxWidth: chatMaxW }}>
              <BooOpsMark
                iconUrl={personaIconUrl}
                emoji={personaEmoji}
                fallbackLetter={personaDisplayName?.slice(0, 1) || 'B'}
              />
              <h1 className="fs-heading text-center font-semibold tracking-tight text-foreground">{personaDisplayName}</h1>
            </div>
          )}
          <div className={cn('w-full', compactEmptyState && 'mt-auto')}>
            <ChatInput
              value={draft}
              onChange={setDraft}
              onSend={send}
              disabled={false}
              streaming={busy}
              onStop={abort}
              activeChatId={null}
              chatMaxW={chatMaxW}
              hidePersonaInMenu={hidePersonaInChatInput}
            />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
      <div className="hidden shrink-0 justify-center border-b border-border py-2 md:flex">
        <ModelSelectorBar {...modelBarProps} />
      </div>
      <div className="mx-auto flex min-h-0 w-full flex-1 flex-col" style={{ maxWidth: chatMaxW }}>
        <div className="min-h-0 flex-1 overflow-hidden">
          {isLoading && !busy ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Loading messages…</div>
          ) : (
            <MessageList
              chatId={activeChatId}
              messages={displayMessages}
              streamingAssistant={busy ? streamText : null}
              sourcesByMessageIndex={sourcesByMessageIndex}
            />
          )}
        </div>
        <div className="shrink-0 px-4 pb-4">
          <ChatInput
            value={draft}
            onChange={setDraft}
            onSend={send}
            disabled={busy}
            streaming={busy}
            onStop={abort}
            activeChatId={activeChatId}
            chatMaxW={chatMaxW}
            hidePersonaInMenu={hidePersonaInChatInput}
          />
        </div>
      </div>
    </div>
  )
}
