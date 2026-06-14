# Delta spec: conversation-export (F3)

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: ChatView SHALL provide a conversation download button

`frontend/src/components/chat/ChatView.jsx` SHALL render a `Button` (variant `ghost`,
size `icon-xs`) with a `Download` icon from `lucide-react` in the chat header area.
The button SHALL render only when `activeChatId` is set, `!isLoading`, and
`messages.length > 0`. The button SHALL be wrapped in a `Tooltip` (components already
present: `frontend/src/components/ui/tooltip.jsx`).

Clicking the button SHALL invoke a `downloadConversation(messages, chatTitle)` helper
that:

1. Filters messages to `role === 'user'` or `role === 'assistant'`, excluding synthetic
   IDs (`__stream__`, `__pending__`, `__optimistic_user__`).
2. Maps each message to a labelled Markdown section: `**You**\n\n{content}` or
   `**Assistant**\n\n{content}`.
3. Strips `<THINKING>...</THINKING>` blocks (including a trailing closed block pattern)
   from assistant message content before export.
4. Joins sections with `\n\n---\n\n`.
5. Creates a `Blob` of type `text/markdown`, triggers a download anchor click, and
   revokes the object URL after.
6. Uses `chat.title` (from the existing `useQuery(['chat', activeChatId])` result) for
   the filename, sanitising with `replace(/[^a-z0-9-_ ]/gi, '_')`. Falls back to
   `'conversation'` if title is null or empty.

No new npm packages are required. `Button`, `Tooltip*`, and `Download` are all
available via existing imports or `lucide-react`.

#### Scenario: Download button appears in an active chat with messages

- **WHEN** `activeChatId` is set, `isLoading` is false, and `messages.length > 0`
- **THEN** the download button SHALL be visible in the chat header area

#### Scenario: Download button is absent when no messages exist

- **WHEN** `activeChatId` is set but `messages.length === 0`
- **THEN** the download button SHALL NOT be rendered

#### Scenario: Download button is absent when no active chat

- **WHEN** `activeChatId` is null
- **THEN** the download button SHALL NOT be rendered

#### Scenario: Clicking download triggers a .md file download

- **WHEN** the user clicks the download button in a chat with 2 user and 2 assistant messages
- **THEN** the browser SHALL initiate a file download
- **AND** the downloaded file SHALL have extension `.md`
- **AND** the file content SHALL contain "**You**" sections for user messages
- **AND** the file content SHALL contain "**Assistant**" sections for assistant messages
- **AND** sections SHALL be separated by `---` dividers
- **AND** THINKING blocks SHALL be stripped from assistant content

#### Scenario: Download filename uses chat title

- **WHEN** `chat.title` is "My Lab Results"
- **THEN** the downloaded file SHALL be named "My Lab Results.md"

#### Scenario: Download filename sanitises special characters

- **WHEN** `chat.title` contains special characters such as `/` or `?`
- **THEN** those characters SHALL be replaced with `_` in the filename
