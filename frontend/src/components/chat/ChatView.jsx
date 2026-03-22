import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { createChat, getChat, listMessages, patchChat } from '@/api/chats.js'
import { useStream } from '@/hooks/useStream.js'
import { useAppStore } from '@/store/index.js'

import { BooOpsMark } from './BooOpsMark.jsx'
import { ChatInput } from './ChatInput.jsx'
import { MessageList } from './MessageList.jsx'
import { ModelSelectorBar } from './ModelSelectorBar.jsx'

export function ChatView() {
  const queryClient = useQueryClient()
  const activeChatId = useAppStore((s) => s.activeChatId)
  const selectedModel = useAppStore((s) => s.selectedModel)
  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const hydrateFromChat = useAppStore((s) => s.hydrateFromChat)
  const personaDisplayName = useAppStore((s) => s.personaDisplayName)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)

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

  async function runStream(chatId, content) {
    const model = selectedModel || undefined
    await consumeStream({
      url: `/api/chats/${chatId}/messages`,
      body: {
        content,
        ...(model ? { model } : {}),
      },
      onToken: (t) => setStreamText((x) => x + t),
      onDone: async () => {
        await queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
        await queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
        setOptimisticUser(null)
        setPendingSend(false)
        setStreamText('')
      },
      onError: async () => {
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
        const newChat = await createChat({ mode: 'booops' })
        await queryClient.invalidateQueries({ queryKey: ['chats'] })
        setActiveChatId(newChat.id)
        hydrateFromChat(newChat)
        const patches = []
        if (selectedModel) patches.push(patchChat(newChat.id, { model: selectedModel }))
        if (webSearchEnabled) patches.push(patchChat(newChat.id, { web_search_enabled: true }))
        await Promise.all(patches)
        await runStream(newChat.id, content)
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
    await runStream(activeChatId, content)
  }

  if (!activeChatId) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-background">
        <div className="hidden shrink-0 justify-center border-b border-border py-2 md:flex">
          <ModelSelectorBar />
        </div>
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center px-4">
          <div className="flex flex-col items-center gap-4">
            <BooOpsMark className="size-20 text-2xl" />
            <h1 className="text-center text-3xl font-semibold tracking-tight text-foreground">{personaDisplayName}</h1>
          </div>
        </div>
        <div className="shrink-0 border-t border-border bg-background">
          <div className="mx-auto w-full max-w-[42rem] px-3 pb-3 pt-2">
            <ChatInput
              value={draft}
              onChange={setDraft}
              onSend={send}
              disabled={false}
              streaming={busy}
              onStop={abort}
              activeChatId={null}
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
      <div className="mx-auto flex min-h-0 w-full max-w-[48rem] flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-hidden">
          {isLoading && !busy ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Loading messages…</div>
          ) : (
            <MessageList messages={displayMessages} streamingAssistant={busy ? streamText : null} />
          )}
        </div>
        <div className="shrink-0 border-t border-border bg-background">
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
      </div>
    </div>
  )
}
