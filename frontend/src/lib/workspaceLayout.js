import { useLayoutStore } from '@/store/layoutStore.js'

/** While Settings layout sliders are dragged, merged over store state until save or close. */
let _liveLayoutDraft = null

export function setWorkspaceLayoutLiveDraft(draft) {
  if (!draft || typeof draft !== 'object') {
    _liveLayoutDraft = null
  } else {
    _liveLayoutDraft = { ...draft }
  }
  applyWorkspaceLayoutToDom()
}

export function clearWorkspaceLayoutLiveDraft() {
  _liveLayoutDraft = null
  applyWorkspaceLayoutToDom()
}

/**
 * Reapply layout prefs (widths + font sizes) to the document root as CSS vars.
 * Reads the persisted layout from useLayoutStore (server-hydrated), then merges
 * any live drag-time draft on top. Without this call, globals.css fallback
 * values render — typography panel saves to the API but the DOM never picks
 * them up unless this runs after hydrate and on each settings change.
 */
export function applyWorkspaceLayoutToDom() {
  const root = document.documentElement
  const persisted = useLayoutStore.getState()
  const layout = _liveLayoutDraft
    ? { ...persisted, ..._liveLayoutDraft }
    : persisted
  if (!layout) return

  if (typeof layout.chatMaxWidth === 'number' && Number.isFinite(layout.chatMaxWidth)) {
    const v = Math.round(layout.chatMaxWidth)
    root.style.setProperty('--chat-max-w', `${v}px`)
    root.style.setProperty('--chat-max-width', `${v}px`)
  }
  if (typeof layout.sidebarWidth === 'number' && Number.isFinite(layout.sidebarWidth)) {
    const v = Math.round(layout.sidebarWidth)
    root.style.setProperty('--sidebar-width', `${v}px`)
  }
  if (typeof layout.sourcesPanelWidth === 'number' && Number.isFinite(layout.sourcesPanelWidth)) {
    const v = Math.round(layout.sourcesPanelWidth)
    root.style.setProperty('--sources-panel-width', `${v}px`)
  }

  const FS_VARS = [
    ['fontSize', '--font-size-base'],
    ['fsNav', '--fs-nav'],
    ['fsChat', '--fs-chat'],
    ['fsInput', '--fs-input'],
    ['fsHeading', '--fs-heading'],
    ['fsCode', '--fs-code'],
  ]
  for (const [key, cssVar] of FS_VARS) {
    const v = layout[key]
    if (typeof v === 'number' && Number.isFinite(v)) {
      root.style.setProperty(cssVar, `${Math.round(v)}px`)
    }
  }
}
