# Delta spec: lab-table-renderer (F4)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: makeMdComponents SHALL include styled table renderers

`makeMdComponents()` in `frontend/src/components/chat/MessageBubble.jsx` SHALL include
component overrides for `table`, `thead`, `tbody`, `tr`, `th`, and `td`.

The `table` renderer SHALL be wrapped in a `div` with `overflow-x-auto` so that wide
lab tables do not overflow the chat bubble on narrow viewports.

`tbody` rows SHALL alternate background color using Tailwind's muted palette
(zebra rows via `[&_tr:nth-child(even)]:bg-muted/20`).

`th` cells SHALL use `text-muted-foreground` and `font-semibold`. `td` cells SHALL use
`text-foreground`.

`remark-gfm` is already listed in `package.json` and already passed to `ReactMarkdown`
in `MessageBubble.jsx`. No new npm packages are required.

#### Scenario: GFM pipe table renders as a styled HTML table

- **WHEN** an assistant message contains a GFM pipe table such as
  `| Test | Result |\n|---|---|\n| HbA1c | 5.7% |`
- **THEN** the rendered output SHALL be an HTML `<table>` element
- **AND** the table SHALL have a visible border
- **AND** the header row SHALL have a distinct background color
- **AND** the table SHALL NOT render as raw pipe-separated text

#### Scenario: Wide table is scrollable on narrow viewports

- **WHEN** an assistant message contains a wide GFM table with many columns
- **THEN** the table container SHALL be horizontally scrollable
- **AND** the chat bubble width SHALL NOT be exceeded

#### Scenario: Zebra rows are applied to tbody

- **WHEN** a table has 4 data rows
- **THEN** even rows SHALL have a different background shade to odd rows

#### Scenario: Non-table Markdown is unaffected

- **WHEN** an assistant message contains only paragraphs, lists, and code blocks
- **THEN** the rendering SHALL be identical to before this change
