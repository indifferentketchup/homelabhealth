# Delta spec: pipeline-trace (F5)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: StreamStatusBar SHALL wrap completed stages in a Collapsible

`frontend/src/components/chat/StreamStatusBar.jsx` SHALL wrap the completed-stages
display in a `Collapsible` / `CollapsibleTrigger` / `CollapsibleContent` from
`frontend/src/components/ui/collapsible.jsx`.

When `completedStages.length > 0`, the trigger SHALL show the count as
"N step completed" (singular) or "N steps completed" (plural).

Each completed stage SHALL render as a `Badge` (variant `outline`) from
`frontend/src/components/ui/badge.jsx` inside the collapsible content area.

The current-phase row (pulsing indicator + phase label + elapsed timer) SHALL remain
outside and below the Collapsible, always visible while streaming. The Collapsible
SHALL NOT wrap the active phase row.

No new npm packages are required. `Collapsible*` and `Badge` are already present in
`frontend/src/components/ui/`.

#### Scenario: No completed stages yields no collapsible

- **WHEN** streaming has just started and `completedStages.length === 0`
- **THEN** no collapsible SHALL be rendered
- **AND** only the active-phase row SHALL be visible

#### Scenario: Collapsible trigger shows count after first stage completes

- **WHEN** `completedStages.length === 1` (e.g. the "rag" phase completed)
- **THEN** a collapsible trigger SHALL be visible with the text "1 step completed"
- **AND** the active-phase row SHALL remain visible below it

#### Scenario: Expanding collapsible shows Badge pills

- **WHEN** the user clicks the collapsible trigger when `completedStages.length === 2`
- **THEN** the content area SHALL expand
- **AND** 2 Badge elements SHALL be visible, each labelled with the corresponding phase name

#### Scenario: Active phase row is always visible during streaming

- **WHEN** the stream is in the "generating" phase
- **THEN** the pulsing indicator, "Generating..." label, and elapsed timer SHALL be visible
  regardless of whether the completed-stages collapsible is open or closed
