# Delta spec: regen-carousel (F6)

**Date:** 2026-06-13

## ADDED Requirements

### Requirement: MessageBubble SHALL provide client-only regeneration history navigation

`frontend/src/components/chat/MessageBubble.jsx` SHALL maintain a `useRef`
(`regenHistoryRef`) that stores the last 2 prior `message.content` strings. The ref is
populated immediately before `onRegenerate` is called, capturing the content that is
about to be replaced.

A `useState` (`regenIndex`) SHALL track which history entry is currently displayed.
`null` means the live current content; a numeric index into `regenHistoryRef.current`
means a prior entry.

Navigation chevrons (`ChevronLeft`, `ChevronRight` from `lucide-react`) inside a
`ButtonGroup` from `frontend/src/components/ui/button-group.jsx` SHALL render below
the assistant bubble when `regenHistoryRef.current.length > 0`.

`regenIndex === null` SHALL display the label "Current". `regenIndex > 0` SHALL display
"Previous N of M".

The content shown inside the bubble (passed to `splitThinking`) and the text copied by
the copy action SHALL both use the currently selected entry (`displayContent`), not
always `message.content`.

`onRegenerate` SHALL always be called with the ORIGINAL `message` object, regardless of
which history entry is being viewed.

History is per-mount only. No persistence is required. Navigating away from the chat
clears the history (component unmount).

No new npm packages are required. `ButtonGroup` is in `frontend/src/components/ui/button-group.jsx`.
`ChevronLeft` and `ChevronRight` are in `lucide-react` (`^0.577.0`).

#### Scenario: No carousel before first regeneration

- **WHEN** the page loads with a conversation that has never been regenerated in this
  browser session
- **THEN** no navigation chevrons SHALL be visible below any assistant bubble

#### Scenario: Carousel appears after first regeneration

- **WHEN** the user clicks Regenerate on an assistant message
- **THEN** the prior response content SHALL be stored in `regenHistoryRef.current`
- **AND** after the new response arrives, navigation chevrons SHALL be visible below
  the new response bubble

#### Scenario: Left chevron navigates to prior response

- **WHEN** the carousel is showing "Current" (regenIndex=null)
- **AND** the user clicks the left chevron
- **THEN** `regenIndex` SHALL be set to 0
- **AND** the bubble body SHALL display the stored prior content
- **AND** the label SHALL show "Previous 1 of 1" (or "Previous 1 of 2")

#### Scenario: Right chevron returns to current response

- **WHEN** `regenIndex === 0`
- **AND** the user clicks the right chevron
- **THEN** `regenIndex` SHALL become `null`
- **AND** the bubble body SHALL display the current `message.content`
- **AND** the label SHALL show "Current"

#### Scenario: Copy action uses selected history entry

- **WHEN** `regenIndex` is 0 (viewing a prior response)
- **AND** the user clicks the copy button
- **THEN** the prior response content SHALL be copied to the clipboard
- **AND** NOT the current `message.content`

#### Scenario: onRegenerate receives original message object

- **WHEN** the user triggers Regenerate from any carousel position
- **THEN** `onRegenerate` SHALL be called with the original `message` prop object
- **AND** NOT with the content currently selected in the carousel

#### Scenario: History is cleared on navigation away

- **WHEN** the user navigates to a different chat and returns
- **THEN** `regenHistoryRef.current` SHALL be empty (component remounted)
- **AND** no carousel SHALL be visible
