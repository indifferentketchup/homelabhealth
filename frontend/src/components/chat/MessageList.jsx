import { useMemo, useState } from 'react'
import { Virtuoso } from 'react-virtuoso'

import { CrisisCard, detectCrisis } from './CrisisCard.jsx'
import { MessageBubble } from './MessageBubble.jsx'

function CompactedGroup({ messages, summary, chatId, onSaveMessageAsNote, onEditUser, onRegenerate }) {
  const [expanded, setExpanded] = useState(false)
  const count = messages.length

  return (
    <div className="my-2 px-4">
      {/* Collapsed header -- always visible */}
      <div className="flex justify-center">
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs text-muted-foreground hover:bg-muted/50 transition-colors"
        >
          <span className="text-[10px]">{expanded ? '▾' : '▸'}</span>
          {count} earlier message{count !== 1 ? 's' : ''} summarized
        </button>
      </div>

      {/* Expanded: show original messages at reduced opacity */}
      {expanded && (
        <div className="mt-2 border-l-2 border-muted pl-3 opacity-50">
          {messages.map((m) => (
            <div key={m.id} className="pb-4">
              <MessageBubble
                chatId={chatId}
                message={m}
                onSaveMessageAsNote={onSaveMessageAsNote}
                onEditUser={onEditUser}
                onRegenerate={onRegenerate}
              />
            </div>
          ))}
        </div>
      )}

      {/* Summary bubble */}
      {summary && (
        <div className="mx-auto my-3 max-w-2xl rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200">
          <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-blue-500">
            Conversation summary
          </div>
          <div className="italic">{summary}</div>
        </div>
      )}
    </div>
  )
}

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
  pruningSummary = null,
}) {
  // Separate compacted messages (consecutive from the start) from active messages.
  const { compactedMessages, activeMessages } = useMemo(() => {
    const compacted = []
    const active = []
    for (const m of messages) {
      if (m.compacted_at) {
        compacted.push(m)
      } else {
        active.push(m)
      }
    }
    return { compactedMessages: compacted, activeMessages: active }
  }, [messages])

  // Tail row while streaming: a synthetic message that either holds the in-flight tokens or, when
  // no token has arrived yet, renders a typing-dots placeholder via MessageBubble's __pending__ id.
  // ChatView commits the real-messages write and the stream-state clear in one flushSync, so by
  // the time `streamingAssistant` is a string, real messages are NOT yet in `messages` — no race.
  const tail =
    streamingAssistant != null
      ? streamingAssistant === ''
        ? [{ id: '__pending__', role: 'assistant', content: '' }]
        : [{ id: '__stream__', role: 'assistant', content: streamingAssistant }]
      : []

  // Build the virtual list data: optional compacted-group sentinel, then active messages, then tail.
  const all = useMemo(() => {
    const items = []
    if (compactedMessages.length > 0) {
      items.push({ id: '__compacted_group__', _compactedGroup: true })
    }
    items.push(...activeMessages, ...tail)
    return items
  }, [compactedMessages, activeMessages, tail])

  return (
    <Virtuoso
      className="h-full min-h-0 w-full"
      data={all}
      followOutput="smooth"
      // iMessage-style anchoring: when the message list is shorter than the
      // viewport (first message, sparse chats), pin items to the bottom so
      // new messages appear just above the input and push older ones up.
      // When the list overflows, behaves normally (oldest scrolled up).
      alignToBottom
      increaseViewportBy={{ top: 600, bottom: 600 }}
      computeItemKey={(_, m) => m.id ?? `idx-${_}`}
      itemContent={(i, m) => {
        // Compacted group sentinel — render the collapsible group + summary.
        if (m._compactedGroup) {
          return (
            <CompactedGroup
              messages={compactedMessages}
              summary={pruningSummary}
              chatId={chatId}
              onSaveMessageAsNote={onSaveMessageAsNote}
              onEditUser={onEditUser}
              onRegenerate={onRegenerate}
            />
          )
        }

        const rowSources = m.role === 'assistant' ? sourcesByMessageIndex[i] : null
        const showRagPill =
          m.id === '__stream__' &&
          streamingRagContext &&
          typeof streamingRagContext.count === 'number' &&
          streamingRagContext.count > 0
        const isLast = i === all.length - 1
        return (
          <div className={`flex flex-col gap-1 px-4 min-w-0 max-w-full overflow-x-hidden ${isLast ? 'pb-1' : 'pb-4'}`}>
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
            {m.role === 'assistant' && detectCrisis(m.content) && <CrisisCard />}
          </div>
        )
      }}
    />
  )
}
