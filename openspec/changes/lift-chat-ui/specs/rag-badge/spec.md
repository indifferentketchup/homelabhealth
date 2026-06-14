# Delta spec: rag-badge (F2)

**Date:** 2026-06-13

## MODIFIED Requirements

### Requirement: Streaming RAG retrieval SHALL display as a Badge component

The streaming RAG retrieval pill SHALL use a `Badge` component instead of a plain text div. The plain-text "RAG: N chunks" pill in `frontend/src/components/chat/MessageList.jsx`
(lines 178-188) SHALL be replaced with a `Badge` (variant `outline`) from
`frontend/src/components/ui/badge.jsx`, accompanied by a `Database` icon from
`lucide-react` (already a project dependency at version `^0.577.0`).

The badge label SHALL pluralise correctly: "1 chunk retrieved" when count is 1,
"N chunks retrieved" when count is not 1.

No new npm packages are required.

#### Scenario: RAG pill shows badge during streaming with 1 chunk

- **WHEN** a message is streaming and `streamingRagContext.count === 1`
- **THEN** the display SHALL show a Badge with a Database icon and the text "1 chunk retrieved"
- **AND** the badge SHALL use variant "outline"

#### Scenario: RAG pill shows badge during streaming with multiple chunks

- **WHEN** a message is streaming and `streamingRagContext.count === 4`
- **THEN** the display SHALL show a Badge with a Database icon and the text "4 chunks retrieved"

#### Scenario: RAG pill is absent when streamingRagContext is null

- **WHEN** `streamingRagContext` is `null` or `streamingRagContext.count` is 0
- **THEN** no RAG badge SHALL be rendered
