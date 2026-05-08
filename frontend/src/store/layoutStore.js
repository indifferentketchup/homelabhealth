import { create } from 'zustand'

import { apiFetch } from '@/api/index.js'

const DEFAULTS = {
  sidebarWidth: 260,
  chatMaxWidth: 1200,
  fontSize: 15,
  fsNav: 13,
  fsChat: 15,
  fsInput: 14,
  fsHeading: 18,
  fsCode: 13,
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
  },

  setSidebarWidth: (val) => set({ sidebarWidth: val }),
  setChatMaxWidth: (val) => set({ chatMaxWidth: val }),
  setFontSize: (val) => set({ fontSize: val }),
  setFsNav: (val) => set({ fsNav: val }),
  setFsChat: (val) => set({ fsChat: val }),
  setFsInput: (val) => set({ fsInput: val }),
  setFsHeading: (val) => set({ fsHeading: val }),
  setFsCode: (val) => set({ fsCode: val }),

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
