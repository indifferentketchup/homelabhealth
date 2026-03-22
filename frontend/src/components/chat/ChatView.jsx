import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { getChat, listMessages } from '@/api/chats.js'
import { useStream } from '@/hooks/useStream.js'
import { useAppStore } from '@/store/index.js'

import { ChatInput } from './ChatInput.jsx'
import { MessageList } from './MessageList.jsx'

export function ChatView() {
  const queryClient = useQueryClient()
  const activeChatId = useAppStore((s) => s.activeChatId)
  const selectedModel = useAppStore((s) => s.selectedModel)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)

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

  const busy = pendingSend

  const displayMessages = pendingSend && optimisticUser ? [...messages, optimisticUser] : messages

  async function send() {
    if (!activeChatId || !draft.trim()) return
    const content = draft.trim()
    setDraft('')
    setPendingSend(true)
    setStreamText('')
    setOptimisticUser({ id: '__optimistic_user__', role: 'user', content })
    const model = selectedModel || undefined
    await consumeStream({
      url: `/api/chats/${activeChatId}/messages`,
      body: {
        content,
        ...(model ? { model } : {}),
      },
      onToken: (t) => setStreamText((x) => x + t),
      onDone: async () => {
        await queryClient.invalidateQueries({ queryKey: ['messages', activeChatId] })
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
        await queryClient.invalidateQueries({ queryKey: ['chat', activeChatId] })
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
      },
      onError: async () => {
        await queryClient.invalidateQueries({ queryKey: ['messages', activeChatId] })
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
      },
    })
  }

  if (!activeChatId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-muted-foreground">
          <p className="text-sm">Select a chat or start a new one from the sidebar.</p>
        </div>
        <ChatInput
          value={draft}
          onChange={setDraft}
          onSend={send}
          disabled
          streaming={false}
          onStop={() => {}}
          activeChatId={null}
        />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="min-h-0 flex-1">
        {isLoading ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Loading messages…</div>
        ) : (
          <MessageList messages={displayMessages} streamingAssistant={busy ? streamText : null} />
        )}
      </div>
      <ChatInput
        value={draft}
        onChange={setDraft}
        onSend={send}
        disabled={busy}
        streaming={busy}
        onStop={abort}
        activeChatId={activeChatId}
      />
    </div>
  )
}
