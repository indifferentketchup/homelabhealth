# Proposal: lift-chat-ui

**Date:** 2026-06-13
**Status:** proposed

## Summary

A focused frontend-only lift of five chat UI improvements: reasoning block auto-open/close
with duration display, a live pipeline step trace during streaming, conversation export to
Markdown, a narrow client-only regeneration history carousel, and an upgraded RAG retrieval
badge. A sixth item -- a GFM table renderer for lab results -- is added because
`makeMdComponents()` in `MessageBubble.jsx` has no `table`/`th`/`td` override, causing
PDF-extracted lab tables to render as raw pipe-separated text.

No backend changes. No new npm dependencies. No schema changes. All primitives
(`Collapsible`, `Badge`, `ButtonGroup`, `ScrollArea`) are already present in
`frontend/src/components/ui/`.

## Motivation

**Reasoning block (ThinkingBlock)** uses a static `<details>` element with no auto-close
after completion and no duration. MedGemma and Qwen reasoning sessions can run for 60-120 s;
the block should open while thinking is in progress and auto-close 1 s after the closing
`</THINKING>` tag arrives, labelling the elapsed time as "Thought for N s". Evidence:
`MessageBubble.jsx:205-235`.

**Pipeline step trace** is ephemeral -- `pipelineEvents` is populated during streaming via
`useStreamOrchestrator.js:372-376` and cleared by `clearStreamUi()`. The existing
`StreamStatusBar` already shows the active phase; completed phases appear as plain checkmarks
with no visual weight. A Collapsible + Badge list per completed stage (rag, reranking,
searching, generating) gives the user feedback that retrieval happened and how many chunks
were found. Evidence: `useStreamOrchestrator.js:132` (`pipelineEvents` state), `useStream.js:90-95`
(`rag_context` SSE event carries `{count, chunks}`), `ChatView.jsx:227/304`
(`pipelineEvents` already passed to `StreamStatusBar`).

**RAG retrieval badge** on the streaming bubble is currently a plain text pill ("RAG: N
chunks") in `MessageList.jsx:182-187`. Upgrading it to a `Badge` variant with a database
icon is a 2-line change that raises visual consistency with the rest of the status strip.

**Conversation export** is ~40 lines. The AI SDK `conversation.tsx` reference uses
`message.parts`; homelabhealth messages use `message.content` directly. The adaptation is
trivial and adds a download button to the chat toolbar area (near copy-message). Evidence:
`MessageBubble.jsx:310` (clipboard copy pattern already there).

**Regeneration history carousel** is scoped to client-only state: the last 2 assistant
responses per `onRegenerate` invocation are kept in a `useRef` inside `MessageBubble`.
`ButtonGroup` + `ChevronLeft`/`ChevronRight` from lucide-react (already a dependency).
No backend read. Evidence: `MessageBubble.jsx:582-598` (existing `onRegenerate` button).

**Lab table renderer** is a gap in `makeMdComponents()`. `remark-gfm` is already a
dependency and already passed to `ReactMarkdown`, so GFM table AST nodes reach the renderer
-- but there are no `table`/`thead`/`tbody`/`tr`/`th`/`td` overrides, so Radix/Tailwind
applies no styles. Lab results from PDF/OCR arrive as GFM tables in the system prompt
context and render correctly only with proper styling. Evidence:
`MessageBubble.jsx:64-132` (`makeMdComponents` has no table entries), `package.json:29`
(`remark-gfm` present).

## Scope

| ID  | File(s) touched                                                              | Type            |
|-----|------------------------------------------------------------------------------|-----------------|
| F1  | `frontend/src/components/chat/MessageBubble.jsx`                             | Feature         |
| F2  | `frontend/src/components/chat/MessageList.jsx`                               | Enhancement     |
| F3  | `frontend/src/components/chat/ChatView.jsx`                                  | Feature         |
| F4  | `frontend/src/components/chat/MessageBubble.jsx`                             | Enhancement     |
| F5  | `frontend/src/components/chat/MessageBubble.jsx`                             | Feature         |
| F6  | `frontend/src/components/chat/MessageBubble.jsx`                             | Bug fix / enhancement |

F1 = Reasoning auto-open/close + duration (replaces ThinkingBlock internals).
F2 = RAG retrieval badge upgrade (streamingRag pill in MessageList).
F3 = Conversation export (new helper + download button in ChatView toolbar).
F4 = Lab-table Markdown renderer (add table overrides to makeMdComponents).
F5 = Pipeline step trace panel (Collapsible in StreamStatusBar or inline below it).
F6 = Regeneration history carousel (client state in MessageBubble).

## Out of scope

- Inline citation chips (Group C): blocked on `sources_used` being populated on message
  INSERT (currently always `null` -- `chats.py:~1718` omits the column) and on the model
  emitting `[N]` citation markers. These are two separate backend changes. The backend
  prerequisite is named "persist sources_used + emit citation markers" and tracked
  separately. No frontend citation work in this change.
- Artifact/file-view side panel (Group B): `sheet.jsx` is absent from
  `frontend/src/components/ui/`. Requires `npx shadcn@latest add sheet` first. Deferred
  as a stretch task -- see Deferred section in tasks.md.
- `motion/react` animations: the package is not in `package.json`. No animation library
  additions in this change; CSS transitions only.
- Any backend route, schema, or Python change.

## Risk

Low overall. All six tasks touch only frontend `.jsx` files. The most fragile file is
`useStream.js` (hard rule #2) -- this change does NOT modify `useStream.js`. `useStreamOrchestrator.js`
is also not modified; pipelineEvents and streamingRag are read-only props already surfaced
to `ChatView`. The `ThinkingBlock` replacement is self-contained inside `MessageBubble.jsx`
and does not change the `splitThinking` parser or any hook.
