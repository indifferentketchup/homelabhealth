const LAYOUT_KEY = 'workspace_layout'

/** While Settings layout sliders are dragged, merged over persisted prefs until save or close. */
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

function readWorkspaceLayout() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    if (!raw) return null
    const j = JSON.parse(raw)
    return j && typeof j === 'object' ? j : null
  } catch {
    return null
  }
}

/**
 * Reapply local layout prefs (widths) on top of current store + CSS variables.
 * Does not inject default title/subtitle — saved branding must override the built-in line.
 */
export function applyWorkspaceLayoutToDom() {
  const root = document.documentElement
  const persisted = readWorkspaceLayout()
  const layout = _liveLayoutDraft
    ? { ...(persisted && typeof persisted === 'object' ? persisted : {}), ..._liveLayoutDraft }
    : persisted
  if (!layout || !Object.keys(layout).length) return

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
}
