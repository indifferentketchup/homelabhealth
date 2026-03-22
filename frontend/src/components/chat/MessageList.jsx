import { useEffect, useRef } from 'react'

import { ScrollArea } from '@/components/ui/scroll-area'

import { MessageBubble } from './MessageBubble.jsx'

export function MessageList({ messages, streamingAssistant }) {
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, streamingAssistant])

  const tail =
    streamingAssistant != null
      ? [{ id: '__stream__', role: 'assistant', content: streamingAssistant }]
      : []

  const all = [...messages, ...tail]

  return (
    <ScrollArea className="h-full min-h-0 w-full flex-1">
      <div className="flex flex-col gap-4 p-4 pb-28">
        {all.map((m) => (
          <MessageBubble key={m.id} message={m} streaming={m.id === '__stream__'} />
        ))}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}
