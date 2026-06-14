# Tasks: lift-chat-ui

**Date:** 2026-06-13

All tasks touch only `frontend/src/`. No backend changes. No new npm dependencies.
Tasks may be applied in any order but the recommended sequence is F4, F2, F1, F3, F5, F6.
After all tasks: `cd frontend && npm run build` must produce zero errors.

Validator findings folded in:
- V1/JD-003: `useRef` is NOT in `MessageBubble.jsx:1` — must be added for F1 and F6.
- V2/JD-001: F6 carousel uses a `useRef` guarded by a JSX ref-length check that never re-renders.
  Fix: use a reactive `useState` counter alongside the ref.
- V3: Auto-close timer not cancelled on manual re-open. Fix: check user-override ref in timer callback.
- V4/JD-002: F3 button condition needs `!busy`. F3 imports are five separate missing symbols.
- JD-004: Export THINKING regex must be global (non-anchored).
- JD-005: Download button placement: after `<WorkspaceTitle />`, before `<DisclaimerBanner />`.
- JD-006: `phaseLabel` is file-private in StreamStatusBar.jsx -- no import needed.
- V6: Collapsible inside aria-live region. Fix: move Collapsible outside the `role="status"` div.

---

## F4 - Add lab-table Markdown renderer to makeMdComponents

**File:** `frontend/src/components/chat/MessageBubble.jsx`
**Time estimate:** 10 min

- [x] In `makeMdComponents()` (`MessageBubble.jsx:64`), after the `blockquote` entry
      (line 128-131), add the following entries before the closing `}`:

      ```jsx
      table: ({ children }) => (
        <div className="my-2 w-full overflow-x-auto rounded-md border border-border">
          <table className="w-full border-collapse text-sm">{children}</table>
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
        <th className="px-3 py-1.5 text-left text-xs font-semibold text-muted-foreground">
          {children}
        </th>
      ),
      td: ({ children }) => (
        <td className="px-3 py-1.5 text-xs text-foreground">{children}</td>
      ),
      ```

- [x] No new imports required for this task alone.
- [x] Run `cd frontend && npm run build` and confirm zero errors.
- [x] Acceptance: in a chat message, a GFM table renders as a bordered, scrollable table
      with zebra rows. Manual check: send a message containing
      `| Col A | Col B |\n|---|---|\n| 1 | 2 |` and confirm it renders as a table.

---

## F2 - Upgrade streaming RAG pill to Badge

**File:** `frontend/src/components/chat/MessageList.jsx`
**Time estimate:** 10 min

- [x] Add the following imports at the top of `MessageList.jsx`:

      ```js
      import { Badge } from '@/components/ui/badge'
      import { Database } from 'lucide-react'
      ```

- [x] In the `showRagPill` block (lines 178-188), replace the inner `<div>` content:

      From:
      ```jsx
      <div className="fs-chat rounded-md border border-border bg-card px-2 py-1.5 text-xs text-muted-foreground">
        RAG: {streamingRagContext.count} chunks
      </div>
      ```

      To:
      ```jsx
      <div className="py-1">
        <Badge variant="outline" className="gap-1.5 text-xs">
          <Database className="size-3" />
          {streamingRagContext.count} chunk{streamingRagContext.count !== 1 ? 's' : ''} retrieved
        </Badge>
      </div>
      ```

- [x] Run `cd frontend && npm run build` and confirm zero errors.
- [x] Acceptance: during an active chat stream with RAG, the pill below the streaming
      bubble shows a badge with a database icon and "N chunk(s) retrieved".

---

## F1 - Reasoning auto-open/close with duration display

**File:** `frontend/src/components/chat/MessageBubble.jsx`
**Time estimate:** 20 min

Note (V1/JD-003): `MessageBubble.jsx:1` currently imports
`{ Children, useEffect, useMemo, useState }`. `useRef` is absent. It MUST be added here.

- [x] On line 1, add `useRef` to the React import:

      ```js
      import { Children, useEffect, useMemo, useRef, useState } from 'react'
      ```

- [x] Add the Collapsible import after the existing `@/components/ui/sources` import:

      ```js
      import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
      ```

- [x] Replace the `ThinkingBlock` function (lines 205-235) with the implementation below.
      Preserve the function name and call-site signature `{ text, mdComponents, inProgress = false }`.

      Note (V3 fix): a `userOverrideRef` tracks manual user interaction. The auto-close
      timer checks this ref before calling `setOpen(false)` so a manual re-open within
      the 1-second window is not overridden.

      ```jsx
      function ThinkingBlock({ text, mdComponents, inProgress = false }) {
        const [open, setOpen] = useState(false)
        const [durationSec, setDurationSec] = useState(null)
        const startedAtRef = useRef(null)
        const autoCloseTimerRef = useRef(null)
        const userOverrideRef = useRef(false) // true if user manually toggled after completion

        function handleOpenChange(next) {
          userOverrideRef.current = true
          setOpen(next)
        }

        useEffect(() => {
          if (inProgress) {
            if (!startedAtRef.current) startedAtRef.current = Date.now()
            userOverrideRef.current = false
            setOpen(true)
            if (autoCloseTimerRef.current) clearTimeout(autoCloseTimerRef.current)
          } else if (startedAtRef.current) {
            const elapsed = Math.round((Date.now() - startedAtRef.current) / 1000)
            setDurationSec(elapsed)
            autoCloseTimerRef.current = setTimeout(() => {
              if (!userOverrideRef.current) setOpen(false)
            }, 1000)
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
          <Collapsible
            open={open}
            onOpenChange={handleOpenChange}
            className="mb-3 rounded-md border border-border/50 bg-muted/30"
          >
            <CollapsibleTrigger className="flex w-full cursor-pointer select-none items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
              {inProgress && (
                <span className="size-1.5 animate-pulse rounded-full bg-primary" aria-hidden />
              )}
              {label}
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="border-t border-border/30 px-3 py-2 text-xs leading-relaxed text-muted-foreground/80">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {text}
                </ReactMarkdown>
              </div>
            </CollapsibleContent>
          </Collapsible>
        )
      }
      ```

- [x] Run `cd frontend && npm run build` and confirm zero errors.
- [x] Acceptance criteria:
      - While `inProgress=true`: block is open, shows pulsing dot and "Reasoning...".
      - 1 s after `inProgress` drops: block auto-closes (unless user re-opened it manually
        within that 1 s window).
      - When closed after completion: trigger shows "Thought for N s".
      - Manual toggle works at all times and is not overridden by the auto-close timer.

---

## F3 - Conversation export (download as Markdown)

**File:** `frontend/src/components/chat/ChatView.jsx`
**Time estimate:** 15 min

Note (V4/JD-002): `ChatView.jsx` has NO existing imports from `lucide-react`, `@/components/ui/button`,
or `@/components/ui/tooltip`. ALL five symbols below must be added.

- [x] Add the following imports to `ChatView.jsx` (alongside the existing named imports):

      ```js
      import { Download } from 'lucide-react'
      import { Button } from '@/components/ui/button'
      import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
      ```

      Confirm before adding: `tooltip.jsx` is present in `frontend/src/components/ui/` (it is).

- [x] Add the following helper function and regex constant in `ChatView.jsx`, above the
      `ChatView` component function.

      Note (JD-004 fix): regex is global and non-anchored so THINKING blocks anywhere in
      the content string are stripped, not only at the start.

      ```js
      const EXPORT_THINKING_RE = /<THINKING>[\s\S]*?<\/THINKING>\s*/g

      function downloadConversation(messages, chatTitle) {
        const exportable = messages.filter(
          (m) => (m.role === 'user' || m.role === 'assistant') &&
                 m.id !== '__optimistic_user__' &&
                 m.id !== '__stream__' &&
                 m.id !== '__pending__',
        )
        if (exportable.length === 0) return
        const sections = exportable.map((m) => {
          const raw = (m.content || '').replace(EXPORT_THINKING_RE, '').trim()
          const label = m.role === 'user' ? '**You**' : '**Assistant**'
          return `${label}\n\n${raw}`
        })
        const md = sections.join('\n\n---\n\n')
        const blob = new Blob([md], { type: 'text/markdown' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${(chatTitle || 'conversation').replace(/[^a-z0-9-_ ]/gi, '_')}.md`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      }
      ```

- [x] Inside the `ChatView` component function, derive the chat title immediately after the
      existing `chat` query result is available:

      ```js
      const chatTitle = chat?.title || null
      ```

- [x] Add the download button in the `activeChatId` branch (the main return at line ~270),
      immediately after `<WorkspaceTitle />` and before `<DisclaimerBanner />`.

      Note (V4 fix): condition includes `!busy` to prevent exporting a truncated conversation
      during an active stream. `busy` is already in scope from `const busy = orch.busy`.

      Note (JD-005 fix): placement is after `<WorkspaceTitle />` (line 273), before
      `<DisclaimerBanner />` (line 275) -- not inside `WorkspaceTitle`.

      ```jsx
      {!busy && !isLoading && messages.length > 0 && (
        <div className="flex justify-end px-4 pb-1">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-xs"
                  className="size-8 text-muted-foreground"
                  onClick={() => downloadConversation(messages, chatTitle)}
                  aria-label="Download conversation"
                >
                  <Download className="size-3.5" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Download conversation</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      )}
      ```

- [x] Run `cd frontend && npm run build` and confirm zero errors.
- [x] Acceptance:
      - Download button is visible in a chat with messages when not streaming.
      - Download button is NOT visible while a stream is in progress (`busy=true`).
      - Clicking the button triggers a `.md` file download.
      - The file contains user/assistant messages separated by `---`, THINKING blocks stripped.
      - Filename is derived from chat title with unsafe chars replaced by `_`.

---

## F5 - Pipeline step trace collapsible in StreamStatusBar

**File:** `frontend/src/components/chat/StreamStatusBar.jsx`
**Time estimate:** 15 min

Note (JD-006): `phaseLabel` is a file-private function defined at line 19 of
`StreamStatusBar.jsx`. No import needed; it is in scope in the replacement snippet.

Note (V6 fix): The Collapsible is placed OUTSIDE (as a sibling above) the
`role="status" aria-live="polite"` div so that interactive button elements and
dynamic badge mutations do not amplify screen-reader announcements of the live region.

- [x] Add imports at the top of `StreamStatusBar.jsx`:

      ```js
      import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
      import { Badge } from '@/components/ui/badge'
      ```

- [x] In the return value of `StreamStatusBar`, wrap the completed-stages section in a
      sibling Collapsible placed ABOVE the existing `<div role="status" ...>` block, not
      inside it. The structure becomes:

      ```jsx
      return (
        <div className={cn('animate-message-in mb-2 flex flex-col gap-1', className)}>
          {completedStages.length > 0 && (
            <Collapsible>
              <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground/70 hover:text-muted-foreground">
                <span className="text-[10px]" aria-hidden>▸</span>
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
          <div
            className="flex flex-col gap-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-muted-foreground shadow-sm"
            role="status"
            aria-live="polite"
            data-testid="stream-status-bar"
          >
            <div className="flex items-center gap-2">
              <span className="inline-block size-2 shrink-0 animate-pulse rounded-full bg-primary" aria-hidden />
              <span className="text-foreground">{phaseLabel(phase, currentModel)}…</span>
              <span className="ml-auto flex items-center gap-2">
                {estimateMs ? (
                  <span className="text-xs text-muted-foreground/60">{formatEstimate(estimateMs)}</span>
                ) : null}
                <span className="font-mono text-xs tabular-nums">{formatElapsed(elapsed)}</span>
              </span>
            </div>
            {phase === 'thinking' ? (
              <span className="text-xs">(CPU inference can take 1-2 min)</span>
            ) : null}
          </div>
        </div>
      )
      ```

      Note: the outer wrapper changes from the existing single status-bar div to a flex
      column that holds the Collapsible above and the status div below. The `animate-message-in`
      class and the `className` prop move to the outer wrapper.

- [x] Run `cd frontend && npm run build` and confirm zero errors.
- [x] Acceptance: during a multi-phase stream, after one phase completes, a "N steps completed"
      collapsible appears above the active-phase row. Expanding it shows Badge pills for each
      completed phase. Screen readers are not spammed with badge mutations.

---

## F6 - Regeneration history carousel

**File:** `frontend/src/components/chat/MessageBubble.jsx`
**Time estimate:** 25 min

Note (V2/JD-001 fix): regeneration forks a new chat and unmounts the original
`MessageBubble` instance. A `useRef` storing history in the component instance is lost.
The fix: use a `useState` counter (`regenCount`) alongside the ref to trigger a re-render.
The carousel remains per-mount (per the non-goals), but the re-render issue is resolved.
The architectural limitation (history lost on fork/nav) is expected and documented.

Note (V1/JD-003): `useRef` must already be added to the React import by task F1. If
applying F6 before F1, add `useRef` to the React import in the same step.

- [x] Confirm (or add if F1 not yet applied) `useRef` in the React import at line 1.

- [x] Add imports to `MessageBubble.jsx` (after the existing ui imports):

      ```js
      import { ButtonGroup } from '@/components/ui/button-group'
      import { ChevronLeft, ChevronRight } from 'lucide-react'
      ```

- [x] Inside the `MessageBubble` function body, after the existing state declarations
      (after `const [copied, setCopied] = useState(false)` at line ~259), add:

      ```js
      const regenHistoryRef = useRef([]) // up to 2 prior content strings; per-mount only
      const [regenIndex, setRegenIndex] = useState(null) // null = current live content
      const [regenCount, setRegenCount] = useState(0) // reactive counter; increment on push
      ```

- [x] Define `displayContent` immediately after the above declarations:

      ```js
      const displayContent = regenIndex !== null
        ? (regenHistoryRef.current[regenIndex] ?? message.content)
        : message.content
      ```

      Note (JD-007): `displayContent` is a `const` declared before the `return` statement.
      All functions that close over it (including `copyText`) read it lazily at call time,
      so declaration order relative to `copyText` does not matter.

- [x] Define `handleRegenerateClick` immediately after `displayContent`:

      ```js
      function handleRegenerateClick() {
        if (message.content) {
          regenHistoryRef.current = [message.content, ...regenHistoryRef.current].slice(0, 2)
          setRegenCount((c) => c + 1) // trigger re-render so carousel guard sees new length
        }
        setRegenIndex(null)
        onRegenerate?.(message) // always passes original message object
      }
      ```

- [x] In the `copyText` function (line 310), replace `message.content` with `displayContent`:

      From: `await navigator.clipboard.writeText(message.content || '')`
      To:   `await navigator.clipboard.writeText(displayContent || '')`

- [x] In the non-user prose branch of the bubble body (`splitThinking` call, line ~436):

      From: `const { thinking, answer, thinkingInProgress } = splitThinking(message.content, streaming)`
      To:   `const { thinking, answer, thinkingInProgress } = splitThinking(displayContent, streaming)`

- [x] Replace the existing regenerate `<Button>` click handler:

      From: `onClick={() => onRegenerate?.(message)}`
      To:   `onClick={handleRegenerateClick}`

- [x] After the existing assistant action row (after the `{forkError ? ... : null}` block,
      around line 601), add the history navigation row. Guard on `regenCount > 0` (reactive
      state, not the ref length, to ensure re-renders fire):

      ```jsx
      {!isUser && !isPendingTyping && regenCount > 0 && (
        <div className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
          <ButtonGroup>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="size-8"
              disabled={regenIndex !== null && regenIndex >= regenHistoryRef.current.length - 1}
              onClick={() =>
                setRegenIndex((i) =>
                  i === null ? 0 : Math.min(i + 1, regenHistoryRef.current.length - 1),
                )
              }
              aria-label="View previous response"
            >
              <ChevronLeft className="size-3.5" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              className="size-8"
              disabled={regenIndex === null}
              onClick={() =>
                setRegenIndex((i) => (i === 0 ? null : i !== null ? i - 1 : null))
              }
              aria-label="View next response"
            >
              <ChevronRight className="size-3.5" />
            </Button>
          </ButtonGroup>
          <span>
            {regenIndex === null
              ? 'Current'
              : `Previous ${regenIndex + 1} of ${regenHistoryRef.current.length}`}
          </span>
        </div>
      )}
      ```

      Note (JD-008): with 1 prior response, the label shows "Previous 1 of 1" and the
      left chevron is disabled (already at the furthest-back entry). This is the correct
      end-state for a single regeneration.

- [x] Run `cd frontend && npm run build` and confirm zero errors.
- [x] Acceptance:
      - No carousel visible before any regeneration.
      - After clicking Regenerate, carousel chevrons appear below the new bubble.
      - Left chevron navigates to prior response; label shows "Previous N of M".
      - Right chevron returns to current response; label shows "Current".
      - Copy action uses the selected (displayed) content.
      - `onRegenerate` receives the original `message` object regardless of carousel position.
      - History is per-mount; navigation away and back clears it.
      - With 1 prior response: label is "Previous 1 of 1", left chevron is disabled.

---

## Cross-cutting verification

- [x] Run `cd frontend && npm run build` with zero errors after all tasks are applied.
- [ ] Manual browser check: open a chat, send a message that triggers RAG and a reasoning
      model. Confirm:
      (a) Reasoning block opens with pulsing dot and "Reasoning...".
      (b) Block auto-closes ~1 s after completion; trigger shows "Thought for N s".
      (c) Manual re-open during the 1-second window is not overridden by the timer.
      (d) RAG pill shows badge with database icon during stream.
      (e) Pipeline steps collapsible appears ABOVE the status bar and expands correctly.
      (f) Screen reader: no announcement flood from badge mutations in the Collapsible.
      (g) Download button appears (not during stream) and triggers a `.md` file.
      (h) Lab table in a message renders with borders and zebra rows.
      (i) After regenerate, chevron nav appears and toggles response content.
      (j) Copy action respects selected history entry.
- [x] Update `CHANGELOG.md` under `[Unreleased]` with a single "UX" section entry
      covering all six improvements.

---

## Deferred (YAGNI)

**Artifact/file-view side panel (Group B):** `sheet.jsx` is absent from
`frontend/src/components/ui/`. Reopen trigger: `npx shadcn@latest add sheet` is run and
`sheet.jsx` confirmed present. No read-only source-content endpoint exists yet.
Defer until: sheet primitive present AND `GET /api/sources/{id}/content` endpoint ships.

**Inline citation chips (Group C):** `sources_used` is always `null` on new messages
(F.md BU-1). `chats.py` stream-path INSERT omits the column (~line 1718).
Backend prerequisite: "persist sources_used + emit citation markers" (separate change).
Do NOT implement until then.
