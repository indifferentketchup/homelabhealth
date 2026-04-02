import { useEffect, useRef, useState } from 'react'

import { ScrollArea } from '@/components/ui/scroll-area'

import { MessageBubble } from './MessageBubble.jsx'

function WebSourcesRow({ sources }) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className="fs-chat rounded-md border"
      style={{
        borderColor: 'var(--border)',
        backgroundColor: 'var(--bg-card)',
        color: 'var(--text-dim)',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="fs-chat flex w-full items-center gap-1 px-2 py-1.5 text-left"
        style={{ color: 'var(--text-dim)' }}
        aria-expanded={open}
      >
        <span aria-hidden>🌐</span> Web Sources {open ? '▴' : '▾'}
      </button>
      {open && (
        <ul className="space-y-1 border-t px-2 py-2" style={{ borderColor: 'var(--border)' }}>
          {sources.map((s, j) => (
            <li key={`${s.url}-${j}`} className="break-words">
              <a
                href={s.url}
                target="_blank"
                rel="noreferrer"
                className="text-primary underline underline-offset-2"
              >
                {s.title || s.url}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function MessageList({
  chatId,
  messages,
  streamingAssistant,
  sourcesByMessageIndex = {},
  streamingRagContext = null,
  onSaveMessageAsNote,
}) {
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
    <ScrollArea className="h-full min-h-0 w-full flex-1 overflow-x-hidden">
      <div className="flex flex-col gap-4 p-4 pb-28">
        {all.map((m, i) => {
          const rowSources = m.role === 'assistant' ? sourcesByMessageIndex[i] : null
          const showRagPill =
            m.id === '__stream__' &&
            streamingRagContext &&
            typeof streamingRagContext.count === 'number' &&
            streamingRagContext.count > 0
          return (
            <div key={m.id} className="flex flex-col gap-1">
              {rowSources?.length ? (
                <div className="flex w-full min-w-0 gap-2 flex-row">
                  <div className="mt-0.5 size-8 shrink-0" aria-hidden />
                  <div className="min-w-0 max-w-[80%]">
                    <WebSourcesRow sources={rowSources} />
                  </div>
                </div>
              ) : null}
              {showRagPill ? (
                <div className="flex w-full min-w-0 gap-2 flex-row">
                  <div className="mt-0.5 size-8 shrink-0" aria-hidden />
                  <div className="min-w-0 max-w-[80%]">
                    <div
                      className="fs-chat rounded-md border px-2 py-1.5 text-xs"
                      style={{
                        borderColor: 'var(--border)',
                        backgroundColor: 'var(--bg-card)',
                        color: 'var(--text-dim)',
                      }}
                    >
                      RAG: {streamingRagContext.count} chunks
                    </div>
                  </div>
                </div>
              ) : null}
              <MessageBubble
                chatId={chatId}
                message={m}
                streaming={m.id === '__stream__'}
                onSaveMessageAsNote={onSaveMessageAsNote}
              />
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  )
}
