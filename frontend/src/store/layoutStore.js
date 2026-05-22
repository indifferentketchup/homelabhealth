import { create } from 'zustand'

import { apiFetch } from '@/api/index.js'

const DEFAULTS = {
  sidebarWidth: 260,
  chatMaxWidth: 1200,
  fontSize: 21,
  fsNav: 20,
  fsChat: 21,
  fsInput: 20,
  fsHeading: 24,
  fsCode: 19,
}

function pickLayoutPayload(data) {
  if (!data || typeof data !== 'object') return {}
  const out = {}
  for (const k of Object.keys(DEFAULTS)) {
    if (data[k] != null) out[k] = data[k]
  }
  return out
}

export const useLayoutStore = create((set, get) => ({
  ...DEFAULTS,

  hydrateFromServer(data) {
    const picked = pickLayoutPayload({ ...DEFAULTS, ...data })
    set(picked)
    // Notify the DOM-applier (workspaceLayout.js) without creating a circular
    // import. WorkspaceApp.jsx already listens on this event.
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('workspace-layout'))
    }
  },

  setFontSize: (val) => set({ fontSize: val }),

  async loadLayout() {
    try {
      const data = await apiFetch('/api/settings/layout')
      get().hydrateFromServer(data)
      return data
    } catch {
      get().hydrateFromServer({})
      return null
    }
  },

  async saveLayout(partial) {
    const out = await apiFetch('/api/settings/layout', { method: 'PATCH', json: partial })
    get().hydrateFromServer(out)
    return out
  },
}))
