import { useAppStore } from '@/store/index.js'

const LAYOUT_KEY = '808notes_layout'

/** While Settings layout sliders are dragged, merged over persisted prefs until save or close. */
let _liveLayoutDraft = null

export function set808notesLayoutLiveDraft(draft) {
  if (!draft || typeof draft !== 'object') {
    _liveLayoutDraft = null
  } else {
    _liveLayoutDraft = { ...draft }
  }
  apply808notesLayoutToDom()
}

export function clear808notesLayoutLiveDraft() {
  _liveLayoutDraft = null
  apply808notesLayoutToDom()
}

export function read808notesLayout() {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY)
    if (!raw) return null
    const j = JSON.parse(raw)
    return j && typeof j === 'object' ? j : null
  } catch {
    return null
  }
}

export function write808notesLayout(partial) {
  const prev = read808notesLayout() || {}
  const next = { ...prev, ...partial }
  localStorage.setItem(LAYOUT_KEY, JSON.stringify(next))
  window.dispatchEvent(new CustomEvent('808notes-layout'))
  return next
}

/**
 * Reapply local layout prefs (widths) on top of current store + CSS variables.
 * Does not inject default title/subtitle — saved 808 branding must override the built-in line.
 */
export function apply808notesLayoutToDom() {
  const root = document.documentElement
  if (root.dataset.mode !== '808notes') return
  const persisted = read808notesLayout()
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

  const cur = useAppStore.getState().branding
  if (!cur || typeof cur !== 'object') return

  const b = { ...cur }
  if (typeof layout.chatMaxWidth === 'number' && Number.isFinite(layout.chatMaxWidth)) {
    b.chatMaxWidth = Math.round(layout.chatMaxWidth)
  }
  if (typeof layout.sidebarWidth === 'number' && Number.isFinite(layout.sidebarWidth)) {
    b.sidebarWidth = Math.round(layout.sidebarWidth)
  }
  if (typeof layout.sourcesPanelWidth === 'number' && Number.isFinite(layout.sourcesPanelWidth)) {
    b.sourcesPanelWidth = Math.round(layout.sourcesPanelWidth)
  }
  useAppStore.getState().setBranding(b)
}
