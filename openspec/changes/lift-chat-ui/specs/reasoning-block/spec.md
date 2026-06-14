# Delta spec: reasoning-block (F1)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: ThinkingBlock SHALL use Collapsible and auto-close with duration

The `ThinkingBlock` component in `frontend/src/components/chat/MessageBubble.jsx` SHALL
be rewritten to use `Collapsible` / `CollapsibleTrigger` / `CollapsibleContent` from
`frontend/src/components/ui/collapsible.jsx` instead of a native `<details>` element.

When `inProgress` becomes `true`, the block SHALL open automatically. When `inProgress`
becomes `false`, the block SHALL auto-close after a 1000 ms delay. The timer SHALL be
cancelled if the component unmounts before it fires.

The elapsed duration from first `inProgress=true` to `inProgress=false` SHALL be computed
(via a `useRef` set on first activation) and displayed as "Thought for N s" in the
collapsed trigger label.

While `inProgress=true` the trigger SHALL show a pulsing indicator and the text
"Reasoning...". When collapsed and duration is known the trigger SHALL show "Thought for N s".
When collapsed and no duration is known the trigger SHALL show "Show reasoning". When open
the trigger SHALL show "Hide reasoning".

The user SHALL be able to manually toggle the block open or closed at any time.

No new npm packages are required. `useRef`, `useState`, `useEffect` are already imported
in `MessageBubble.jsx`.

#### Scenario: Block opens automatically when reasoning starts

- **WHEN** a message begins streaming with an open `<THINKING>` tag (i.e. `inProgress=true`)
- **THEN** the ThinkingBlock SHALL be open (visible content area)
- **AND** the trigger SHALL display "Reasoning..." with a pulsing indicator

#### Scenario: Block auto-closes 1s after reasoning completes

- **WHEN** the `</THINKING>` closing tag is received and `inProgress` drops to `false`
- **THEN** the ThinkingBlock SHALL remain open for approximately 1000 ms
- **AND** after the delay the block SHALL close
- **AND** the trigger label SHALL display "Thought for N s" where N is the elapsed seconds

#### Scenario: User can manually toggle the block

- **WHEN** the user clicks the CollapsibleTrigger while the block is open
- **THEN** the block SHALL close
- **WHEN** the user clicks again
- **THEN** the block SHALL reopen

#### Scenario: Timer is cancelled on unmount

- **WHEN** the component unmounts while the auto-close timer is pending
- **THEN** the timer SHALL be cancelled (no setState call on unmounted component)

#### Scenario: Completed reasoning on a loaded message shows Show/Hide

- **WHEN** a historical assistant message has a complete `<THINKING>...</THINKING>` block
  (not streaming, `inProgress=false`)
- **AND** the component mounts for the first time for that message (no prior `inProgress=true` transition on this mount)
- **THEN** the block SHALL be closed by default with trigger label "Show reasoning"
