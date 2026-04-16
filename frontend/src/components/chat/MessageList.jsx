import { useState } from 'react'
import { Virtuoso } from 'react-virtuoso'

import { MessageBubble } from './MessageBubble.jsx'

function WebSourcesRow({ sources }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="fs-chat rounded-md border border-border bg-card text-muted-foreground">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="fs-chat flex w-full items-center gap-1 px-2 py-1.5 text-left text-muted-foreground"
        aria-expanded={open}
      >
        <span aria-hidden>🌐</span> Web Sources {open ? '▴' : '▾'}
      </button>
      {open && (
        <ul className="space-y-1 border-t border-border px-2 py-2">
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
  onEditUser,
  onRegenerate,
}) {
  // Tail row while streaming: a synthetic message that either holds the in-flight tokens or, when
  // no token has arrived yet, renders a typing-dots placeholder via MessageBubble's __pending__ id.
  const tail =
    streamingAssistant != null
      ? streamingAssistant === ''
        ? [{ id: '__pending__', role: 'assistant', content: '' }]
        : [{ id: '__stream__', role: 'assistant', content: streamingAssistant }]
      : []

  const all = [...messages, ...tail]

  return (
    <Virtuoso
      className="h-full min-h-0 w-full"
      data={all}
      followOutput="smooth"
      increaseViewportBy={{ top: 600, bottom: 600 }}
      computeItemKey={(_, m) => m.id ?? `idx-${_}`}
      itemContent={(i, m) => {
        const rowSources = m.role === 'assistant' ? sourcesByMessageIndex[i] : null
        const showRagPill =
          m.id === '__stream__' &&
          streamingRagContext &&
          typeof streamingRagContext.count === 'number' &&
          streamingRagContext.count > 0
        const isLast = i === all.length - 1
        return (
          <div className={`flex flex-col gap-1 px-4 ${isLast ? 'pb-28' : 'pb-4'}`}>
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
                  <div className="fs-chat rounded-md border border-border bg-card px-2 py-1.5 text-xs text-muted-foreground">
                    RAG: {streamingRagContext.count} chunks
                  </div>
                </div>
              </div>
            ) : null}
            <MessageBubble
              chatId={chatId}
              message={m}
              streaming={m.id === '__stream__' || m.id === '__pending__'}
              onSaveMessageAsNote={onSaveMessageAsNote}
              onEditUser={onEditUser}
              onRegenerate={onRegenerate}
            />
          </div>
        )
      }}
    />
  )
}
