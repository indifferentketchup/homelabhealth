## MODIFIED Requirements

### Requirement: SidebarLink component extracts link pattern
A `SidebarLink({ icon, label, to, collapsed, onClick, ariaLabel })` component SHALL be extracted to replace the 6+ collapsed/expanded link patterns.
**Reason**: Audit finding S10 -- each nav link has a collapsed (icon-only) and expanded (icon+label) variant with near-identical JSX (lines 403-452, 569-599, 601-614, 632-636, 668-700, 718-743).
**Migration**: None -- behavior-preserving refactor.

#### Scenario: Expanded sidebar shows icon and label
- **WHEN** the sidebar is expanded and a `SidebarLink` renders
- **THEN** both the icon and the text label are visible

#### Scenario: Collapsed sidebar shows icon only
- **WHEN** the sidebar is collapsed and a `SidebarLink` renders
- **THEN** only the icon is visible, with no text label

### Requirement: renameChat helper extracts rename logic
A `renameChat(chatId, title)` helper SHALL replace both `commitRename` and `commitRenameFromPrompt`.
**Reason**: Audit finding S8 -- `commitRename` (lines 281-291) and `commitRenameFromPrompt` (lines 293-301) have identical logic except the title source.
**Migration**: None -- behavior-preserving refactor.

#### Scenario: Inline rename uses helper
- **WHEN** the user renames a chat via the inline edit input (desktop)
- **THEN** `renameChat(chatId, title)` is called, which patches the chat and invalidates the query cache

#### Scenario: Prompt rename uses helper
- **WHEN** the user renames a chat via `window.prompt` (collapsed sidebar)
- **THEN** `renameChat(chatId, title)` is called with the same behavior

### Requirement: no new UI primitive imports
No new imports from `frontend/src/components/ui/` SHALL be added for the SidebarLink extraction.
**Reason**: CLAUDE.md hard rule #1 -- check `frontend/src/components/ui/` before importing primitives.

#### Scenario: SidebarLink uses existing Button primitive
- **WHEN** `SidebarLink` is implemented
- **THEN** it uses the existing `Button` component from `@/components/ui/button` (already imported) or native elements, with no new ui/ imports
