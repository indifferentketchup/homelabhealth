# Changelog

All notable user-facing and developer-facing changes to BooLab. Dates are `YYYY-MM-DD`.

## 2026-04-16

### UI
- **Skills Library: wider "Add Skill" dialog.** Bumped the modal from `max-w-3xl` → `max-w-5xl`, tightened the sidebar (`w-52` → `w-48`), and increased padding so URL and search inputs are no longer cramped. Input height is now `h-10` (was `h-8`); Name/Tags in the manual tab share a two-column row on wider screens.
  - File: `frontend/src/pages/SkillsLibraryPage.jsx`
- **Settings → Skills tab.** Added a Skills tab to the shared Settings page that embeds the full Skills Library CRUD. Available in both BooOps and 808notes settings.
  - Files: `frontend/src/pages/booops/SettingsPage.jsx`
- **808notes: sources panel collapse button alignment.** The collapse button used to jump down (`mt-12`) to clear the old profile button, which has been removed. It now stays locked to the top-right of the panel in both expanded and collapsed states, so the transition is smooth.
  - File: `frontend/src/pages/notes808/Notes808Workspace.jsx`

### Docs
- **`CLAUDE.md`** — added Zustand / TanStack Query to the stack summary, a partial-UI rebuild command, clarified that modes are selected via `VITE_APP_MODE` + `ModeRouter`, and expanded the Key Frontend Files table (ModeRouter, branding, stores, SettingsPage-sharing gotcha, SourcesPanel, SkillsLibraryPage). Removed a stale reference to a nonexistent `getStoredBoolabToken()` helper.
- **`README.md`** — noted the skills library in the tagline, corrected the inference stack (Bifrost → llama-swap → llama.cpp with infinity-emb / infinity-rerank), and linked this changelog.
