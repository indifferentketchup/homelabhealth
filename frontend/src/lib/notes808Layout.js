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

/** Reapply local layout prefs (widths) on top of current store + CSS variables. */
export function apply808notesLayoutToDom() {
  const root = document.documentElement
  if (root.dataset.mode !== '808notes') return
  const persisted = read808notesLayout()
  const layout = _liveLayoutDraft
    ? { ...(persisted && typeof persisted === 'object' ? persisted : {}), ..._liveLayoutDraft }
    : persisted
  if (!layout || !Object.keys(layout).length) return
  const cur = useAppStore.getState().branding || {}
  const b = { ...cur }
  if (typeof layout.chatMaxWidth === 'number' && Number.isFinite(layout.chatMaxWidth)) {
    const v = Math.round(layout.chatMaxWidth)
    b.chatMaxWidth = v
    root.style.setProperty('--chat-max-w', `${v}px`)
    root.style.setProperty('--chat-max-width', `${v}px`)
  }
  if (typeof layout.sidebarWidth === 'number' && Number.isFinite(layout.sidebarWidth)) {
    const v = Math.round(layout.sidebarWidth)
    b.sidebarWidth = v
    root.style.setProperty('--sidebar-width', `${v}px`)
  }
  if (typeof layout.sourcesPanelWidth === 'number' && Number.isFinite(layout.sourcesPanelWidth)) {
    const v = Math.round(layout.sourcesPanelWidth)
    b.sourcesPanelWidth = v
    root.style.setProperty('--sources-panel-width', `${v}px`)
  }
  useAppStore.getState().setBranding(b)
}
