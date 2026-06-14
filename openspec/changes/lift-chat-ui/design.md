# Design: lift-chat-ui

**Date:** 2026-06-13

---

## Validator findings (folded 2026-06-13)

- **V1/JD-003:** `MessageBubble.jsx:1` does NOT import `useRef`. Both F1 and F6 require it.
  Fix: add `useRef` to the React import line in task F1 (and F6 if applied separately).
- **V2/JD-001:** F6 carousel cannot persist across regenerations because `handleRegenerate`
  calls `forkAndStream` which changes `activeChatId` and unmounts the `MessageBubble`
  instance. The `regenHistoryRef` is lost. History is per-mount only (documented non-goal).
  The render-trigger problem (ref mutation not causing re-render) is fixed by adding
  a reactive `useState` counter `regenCount` incremented alongside ref pushes.
- **V3:** Auto-close timer was not cancelled when the user manually re-opened the block.
  Fix: `userOverrideRef` checked in the timer callback before calling `setOpen(false)`.
- **V4/JD-002:** F3 download button must gate on `!busy` (not just `!isLoading`) to prevent
  exporting a truncated conversation during streaming. `ChatView.jsx` has zero existing
  imports from lucide-react, button, or tooltip -- all five symbols must be added.
- **JD-004:** Export THINKING regex must be global (`/g` flag, no `^` anchor) to catch
  THINKING blocks that do not start at position 0 of the string.
- **JD-005:** Download button placement is after `<WorkspaceTitle />`, before
  `<DisclaimerBanner />` -- not inside `WorkspaceTitle`.
- **JD-006:** `phaseLabel` is file-private in `StreamStatusBar.jsx` -- no import needed.
- **V6:** Collapsible with interactive trigger inside `role="status" aria-live="polite"`
  causes screen-reader announcement flood on stage transitions. Fix: move Collapsible
  to a sibling element above the status div.

---

## Must Have

- All changes are pure frontend JSX/JS. Zero backend modifications.
- No new npm dependencies added (all primitives present; `@radix-ui/react-use-controllable-state`
  already in `package.json:16` for optional use; `remark-gfm` present).
- ESM only -- no `require()`, no CommonJS.
- Hard rule #1 enforced: only import from `frontend/src/components/ui/` components that
  already exist. Confirmed present: `Collapsible`/`CollapsibleTrigger`/`CollapsibleContent`,
  `Badge`, `ButtonGroup`/`ButtonGroupText`, `ScrollArea`.
- Hard rule #2 enforced: `useStream.js` is NOT modified by any task in this change.
- `sheet.jsx` and `motion/react` are absent; no task may import them.

## Must NOT Have

- No changes to `useStream.js`, `useDurableChat.js`, or any hook file.
- No new API endpoints or fetch calls.
- No changes to `backend/`.
- No inline citation work (Group C -- backend-blocked per F.md finding 1 / BU-1 / BU-3).

---

## F1 - Reasoning auto-open/close + duration

### Problem

`ThinkingBlock` (`MessageBubble.jsx:205-235`) uses a native `<details>` element. State
is managed with a single `userClosed` boolean. There is no timer, no duration tracking,
and no auto-close after the reasoning completes.

```jsx
// current -- no duration, no auto-close timer
const isOpen = inProgress ? !userClosed : false
```

After `inProgress` drops to `false` (the `</THINKING>` tag is fully received),
`isOpen` becomes `false` immediately -- the block closes with no label, discarding
user context about how long reasoning took.

### Fix

Replace `ThinkingBlock`'s internal logic with:

1. A `useRef` (`startedAtRef`) set when `inProgress` transitions from `false` to `true`.
2. A `useState` (`durationSec`) set when `inProgress` transitions from `true` to `false`.
3. A `useEffect` that fires when `inProgress` drops to `false`: computes
   `Math.round((Date.now() - startedAtRef.current) / 1000)` and sets `durationSec`.
4. Auto-open: when `inProgress` becomes `true`, set `open = true` unless the user has
   manually closed it.
5. Auto-close: after `inProgress` drops to `false`, a `setTimeout` of 1000 ms calls
   `setOpen(false)` unless the user has re-opened it. Cancel the timer on unmount.
6. Summary label: when closed and `durationSec > 0`, show "Thought for N s" in the
   `<summary>`. When open, show "Hide reasoning" as now.

Replace `<details>` with the existing `Collapsible`/`CollapsibleTrigger`/`CollapsibleContent`
from `frontend/src/components/ui/collapsible.jsx` for consistent keyboard + ARIA behavior.

```jsx
// sketch
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'

function ThinkingBlock({ text, mdComponents, inProgress = false }) {
  const [open, setOpen] = useState(false)
  const [durationSec, setDurationSec] = useState(null)
  const startedAtRef = useRef(null)
  const autoCloseTimerRef = useRef(null)

  useEffect(() => {
    if (inProgress) {
      if (!startedAtRef.current) startedAtRef.current = Date.now()
      setOpen(true)
      if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current)
    } else if (startedAtRef.current) {
      const elapsed = Math.round((Date.now() - startedAtRef.current) / 1000)
      setDurationSec(elapsed)
      autoCloseTimerRef.current = setTimeout(() => setOpen(false), 1000)
    }
    return () => {
      if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current)
    }
  }, [inProgress])

  if (!text) return null
  const label = inProgress
    ? 'Reasoning...'
    : durationSec != null
      ? (open ? 'Hide reasoning' : `Thought for ${durationSec} s`)
      : (open ? 'Hide reasoning' : 'Show reasoning')

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mb-3 rounded-md border border-border/50 bg-muted/30">
      <CollapsibleTrigger className="flex w-full cursor-pointer select-none items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
        {inProgress && <span className="size-1.5 animate-pulse rounded-full bg-primary" />}
        {label}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="border-t border-border/30 px-3 py-2 text-xs leading-relaxed text-muted-foreground/80">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{text}</ReactMarkdown>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
```

The `useRef` pattern avoids adding `startedAt` to state (no re-render when set).

---

## F2 - RAG retrieval badge upgrade

### Problem

`MessageList.jsx:182-187` renders the streaming RAG context as a plain text div:

```jsx
<div className="fs-chat rounded-md border border-border bg-card px-2 py-1.5 text-xs text-muted-foreground">
  RAG: {streamingRagContext.count} chunks
</div>
```

This is visually inconsistent with the Badge components used elsewhere in the codebase.

### Fix

Replace the plain div with a `Badge` from `frontend/src/components/ui/badge.jsx`, variant
`outline`, with a `DatabaseIcon` from lucide-react:

```jsx
import { Badge } from '@/components/ui/badge'
import { Database } from 'lucide-react'

// inside the showRagPill block:
<Badge variant="outline" className="gap-1 text-xs">
  <Database className="size-3" />
  {streamingRagContext.count} chunks retrieved
</Badge>
```

`lucide-react` is already a dependency (`package.json:21`). This is a 2-line delta.

---

## F3 - Conversation export

### Problem

There is no way to export a chat conversation. The copy button (`MessageBubble.jsx:310`)
copies a single message. Users cannot save a full thread as a document.

### Fix

Add a `downloadConversation(messages)` helper to `ChatView.jsx` (or a small local util)
that:

1. Filters messages to `role === 'user'` or `role === 'assistant'`.
2. Maps each to a Markdown section:
   - `**You:** <content>` for user messages
   - `**Assistant:** <content>` for assistant messages, stripping `<THINKING>...</THINKING>` blocks.
3. Joins with `\n\n---\n\n` separators.
4. Creates a `Blob('text/markdown')`, a temporary object URL, clicks an anchor, then revokes.

Add a download icon button to the chat toolbar in `ChatView.jsx`. The button renders only
when `!busy && messages.length > 0`. Use `DownloadIcon` from lucide-react and the existing
`Button` component.

```jsx
// sketch for downloadConversation
function downloadConversation(messages, chatTitle) {
  const THINKING_RE = /^<THINKING>[\s\S]*?<\/THINKING>\s*/
  const lines = messages
    .filter((m) => m.role === 'user' || m.role === 'assistant')
    .map((m) => {
      const text = (m.content || '').replace(THINKING_RE, '').trim()
      const label = m.role === 'user' ? '**You**' : '**Assistant**'
      return `${label}\n\n${text}`
    })
  const md = lines.join('\n\n---\n\n')
  const blob = new Blob([md], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${chatTitle || 'conversation'}.md`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
```

The button placement is below `WorkspaceTitle` in the chat header row, adjacent to the
existing overflow area.

---

## F4 - Lab-table Markdown renderer

### Problem

`makeMdComponents()` (`MessageBubble.jsx:64-132`) provides no `table`, `thead`, `tbody`,
`tr`, `th`, or `td` overrides. `remark-gfm` is already passed to `ReactMarkdown` and
parses GFM pipe tables into the AST, but without component overrides the table renders as
plain text (the default browser `<table>` with no styles). Lab results extracted from PDFs
via `pdfplumber` or OCR are often GFM tables.

### Fix

Add table component overrides to `makeMdComponents()`:

```jsx
table: ({ children }) => (
  <div className="my-2 w-full overflow-x-auto rounded-md border border-border">
    <table className="w-full text-sm border-collapse">{children}</table>
  </div>
),
thead: ({ children }) => (
  <thead className="border-b border-border bg-muted/50">{children}</thead>
),
tbody: ({ children }) => (
  <tbody className="divide-y divide-border [&_tr:nth-child(even)]:bg-muted/20">{children}</tbody>
),
tr: ({ children }) => <tr>{children}</tr>,
th: ({ children }) => (
  <th className="px-3 py-1.5 text-left text-xs font-semibold text-muted-foreground">{children}</th>
),
td: ({ children }) => (
  <td className="px-3 py-1.5 text-xs text-foreground">{children}</td>
),
```

The `overflow-x-auto` wrapper ensures narrow-viewport safety. The zebra-row `[&_tr:nth-child(even)]`
selector matches the existing muted palette.

---

## F5 - Pipeline step trace panel

### Problem

Completed pipeline stages appear in `StreamStatusBar` as plain `✅ <label>` rows with no
additional detail. The `pipelineEvents` array (already passed to `StreamStatusBar` as a
prop) records `{phase, model, estimate_ms}` for each stage. The `rag_context` SSE event
populates `streamingRag` (`useStreamOrchestrator.js:148`, `useStream.js:90-95`) with
`{count, chunks}` but this data is not displayed inside the status bar.

### Fix

Wrap the completed-stages section of `StreamStatusBar` in a `Collapsible` that shows a
summary count label ("N steps") as the trigger and expands to show each stage as a `Badge`:

```jsx
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { Badge } from '@/components/ui/badge'

// inside StreamStatusBar, replacing the completedStages.map:
{completedStages.length > 0 && (
  <Collapsible>
    <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground/70 hover:text-muted-foreground">
      <span className="text-[10px]">▸</span>
      {completedStages.length} step{completedStages.length !== 1 ? 's' : ''} completed
    </CollapsibleTrigger>
    <CollapsibleContent>
      <div className="mt-1 flex flex-wrap gap-1">
        {completedStages.map((e, i) => (
          <Badge key={i} variant="outline" className="gap-1 text-xs">
            <span>✅</span>
            {phaseLabel(e.phase, e.model)}
          </Badge>
        ))}
      </div>
    </CollapsibleContent>
  </Collapsible>
)}
```

This is purely additive to `StreamStatusBar.jsx` -- the current phase row and elapsed
time are unchanged.

---

## F6 - Regeneration history carousel

### Problem

When `onRegenerate` is called, the previous assistant response is discarded (fork creates
a new chat). There is no way to navigate back to a prior response within the same message
position. The `ButtonGroup` primitive is already present but unused in `MessageBubble.jsx`.

### Fix

Add a `useRef` (`regenHistoryRef`) to `MessageBubble` that accumulates up to 2 prior
assistant `message.content` values when `onRegenerate` is invoked. A `useState`
(`regenIndex`) controls which entry is shown. Navigation buttons (`ChevronLeft`,
`ChevronRight`) appear below the message bubble (alongside the existing action row) when
`regenHistoryRef.current.length > 0`. Wrapped in a `ButtonGroup`.

Key invariant: the ref is populated BEFORE calling `onRegenerate`, capturing the content
that is about to be replaced. On initial mount the ref is empty; only after at least one
regeneration does the carousel appear.

```jsx
// sketch
const regenHistoryRef = useRef([])
const [regenIndex, setRegenIndex] = useState(null) // null = live (current)

function handleRegenerateClick() {
  if (regenHistoryRef.current.length < 2) {
    regenHistoryRef.current = [message.content, ...regenHistoryRef.current]
  }
  setRegenIndex(null)
  onRegenerate?.(message)
}

// displayed content when browsing history:
const displayContent = regenIndex !== null
  ? regenHistoryRef.current[regenIndex]
  : message.content
```

The displayed content swaps the `message.content` read inside the bubble body via a
`displayContent` derived variable. This does NOT mutate the message object.

Caveat: history is per-mount only -- navigation away clears it. This is by design (no
persistence required per F.md finding 6).

---

## Dependency ordering

All six tasks are independent. Recommended sequence: F4 first (safest, isolated),
then F2 (1-liner), then F1 (most behaviorally visible), then F3, then F5, then F6.
F6 is highest behaviorally risk due to the `displayContent` swap and should be last.

---

## Backward compat

All changes are additive. No existing prop signatures change. `ThinkingBlock` is not
exported -- it is a file-private component -- so the Collapsible replacement does not
affect any external consumer.

---

## Backend prerequisite (Group C - out of scope)

Inline citation chips are blocked on two backend changes:

1. Populate `sources_used` column on message INSERT in the stream handler
   (`backend/routers/chats.py` stream path, around line 1718) with RAG chunk metadata
   `{id, name, original_url, chunk_text}` from `_assembled_system_prompt`.
2. Prompt the model (or post-process its output) to emit `[N]` citation markers aligned
   to the `sources_used` array. BU-3 (F.md): `InlineCitationCardTrigger` assumes HTTP
   URLs; health records use file paths -- adaptation needed.

Track as: "persist sources_used + emit citation markers" (separate backend change).

---

## Stretch tasks (Group B)

Artifact/file-view side panel requires `npx shadcn@latest add sheet` first. Once
`sheet.jsx` is present in `frontend/src/components/ui/`, a read-only file-view dialog can
be added to the sources panel. Not in scope for this change.
