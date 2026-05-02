import { create } from 'zustand'

import { fetchMe } from '@/api/profile.js'

const USER_PROFILE_STORAGE_KEY = 'homelabhealth-user-profile-v1'

function normalizeUserProfile(raw) {
  if (!raw || typeof raw !== 'object') {
    return { displayName: 'You', emoji: '👤', bio: '', avatarDataUrl: '' }
  }
  const avatar =
    typeof raw.avatarDataUrl === 'string' && raw.avatarDataUrl.startsWith('data:image/')
      ? raw.avatarDataUrl
      : ''
  return {
    displayName: (raw.displayName != null && String(raw.displayName).trim()) || 'You',
    emoji: raw.emoji != null ? String(raw.emoji).trim() : '👤',
    bio: typeof raw.bio === 'string' ? raw.bio : '',
    avatarDataUrl: avatar,
  }
}

function loadUserProfileFromStorage() {
  try {
    const json = localStorage.getItem(USER_PROFILE_STORAGE_KEY)
    if (!json) return normalizeUserProfile(null)
    return normalizeUserProfile(JSON.parse(json))
  } catch {
    return normalizeUserProfile(null)
  }
}

/** Default persona, looked up from a personas list. */
export function defaultPersona(personas) {
  const list = Array.isArray(personas) ? personas : []
  return list.find((x) => x.is_default_808notes) ?? null
}

/** Map API persona row → store display fields (also used after AI settings refetch). */
export function personaFieldsFromRecord(p) {
  if (!p) {
    return {
      personaDisplayName: 'Assistant',
      personaIconUrl: null,
      personaEmoji: '🤖',
    }
  }
  return {
    personaDisplayName: (p.name && String(p.name).trim()) || 'Assistant',
    personaIconUrl: p.icon_url || null,
    personaEmoji: (p.avatar_emoji && String(p.avatar_emoji).trim()) || '🤖',
  }
}

function personaToUi(p) {
  return personaFieldsFromRecord(p)
}

function revokeProfileIconObjectUrl(url) {
  if (url && String(url).startsWith('blob:')) {
    try {
      URL.revokeObjectURL(url)
    } catch {
      /* ignore */
    }
  }
}

export const useAppStore = create((set, get) => ({
  currentUser: null,
  /** `/api/auth/profile/icon-asset` cached as blob URL. */
  profileIconObjectUrl: null,
  setCurrentUser: (user) => set({ currentUser: user }),
  syncUserProfileFromServer: async (me) => {
    if (!me) return
    revokeProfileIconObjectUrl(get().profileIconObjectUrl)
    let profileIconObjectUrl = null
    if (me.icon_url) {
      try {
        const res = await fetch('/api/auth/profile/icon-asset')
        if (res.ok) {
          const blob = await res.blob()
          profileIconObjectUrl = URL.createObjectURL(blob)
        }
      } catch {
        /* ignore */
      }
    }
    const userProfile = normalizeUserProfile({
      displayName: me.display_name,
      emoji: me.avatar_emoji,
      bio: me.bio,
      avatarDataUrl: '',
    })
    try {
      localStorage.setItem(USER_PROFILE_STORAGE_KEY, JSON.stringify(userProfile))
    } catch {
      /* ignore */
    }
    set({ userProfile, profileIconObjectUrl })
  },
  bootstrapAuth: async () => {
    try {
      const me = await fetchMe()
      set({ currentUser: me })
      await get().syncUserProfileFromServer(me)
    } catch {
      revokeProfileIconObjectUrl(get().profileIconObjectUrl)
      set({ currentUser: null, profileIconObjectUrl: null })
    }
  },

  chats: [],
  setChats: (chats) => set({ chats: Array.isArray(chats) ? chats : [] }),

  activeChatId: null,
  setActiveChatId: (id) => set({ activeChatId: id }),

  messages: [],
  setMessages: (messages) => set({ messages: Array.isArray(messages) ? messages : [] }),

  selectedModel: null,
  setSelectedModel: (model) => set({ selectedModel: model }),

  /** Last known default from GET /api/inference/settings */
  defaultModel: null,
  setDefaultModel: (model) => set({ defaultModel: model ?? null }),

  webSearchEnabled: false,
  setWebSearchEnabled: (enabled) => set({ webSearchEnabled: Boolean(enabled) }),

  personaDisplayName: 'Assistant',
  personaIconUrl: null,
  personaEmoji: '🤖',
  setPersonaIconUrl: (url) => set({ personaIconUrl: url ?? null }),
  setPersonaEmoji: (emoji) => set({ personaEmoji: emoji || '🤖' }),

  /** Default persona for new chats (initialized from API default) */
  activePersonaId: null,
  setActivePersonaId: (id) =>
    set((s) => {
      if (!id) {
        const def = defaultPersona(s.personas)
        if (def) return { activePersonaId: def.id, ...personaToUi(def) }
        return { activePersonaId: null, ...personaToUi(null) }
      }
      const p = s.personas.find((x) => x.id === id)
      if (p) return { activePersonaId: id, ...personaToUi(p) }
      return { activePersonaId: id }
    }),

  personas: [],
  setPersonas: (list) =>
    set((s) => {
      const personas = Array.isArray(list) ? list : []
      let activePersonaId = s.activePersonaId
      if (activePersonaId && !personas.some((x) => x.id === activePersonaId)) {
        activePersonaId = null
      }
      if (!activePersonaId) {
        const def = defaultPersona(personas)
        if (def) {
          return {
            personas,
            activePersonaId: def.id,
            ...personaToUi(def),
          }
        }
        return { personas, ...personaToUi(null), activePersonaId: null }
      }
      const p = personas.find((x) => x.id === activePersonaId)
      if (!p) return { personas, activePersonaId }
      return {
        personas,
        activePersonaId,
        ...personaToUi(p),
      }
    }),

  /** Optional default workspace (prompt context) for new chats */
  activeWorkspaceId: null,
  setActiveWorkspaceId: (id) => set({ activeWorkspaceId: id }),

  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: Boolean(open) }),

  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: Boolean(open) }),

  /** Merged branding (for layout tokens e.g. sidebar width); updated when CSS is applied */
  branding: null,
  setBranding: (branding) => set({ branding }),

  /** Local-only user profile (localStorage) */
  userProfile: loadUserProfileFromStorage(),
  hydrateUserProfile: () => set({ userProfile: loadUserProfileFromStorage() }),
  setUserProfile: (patch) =>
    set((s) => {
      const next = normalizeUserProfile({ ...s.userProfile, ...patch })
      try {
        localStorage.setItem(USER_PROFILE_STORAGE_KEY, JSON.stringify(next))
      } catch {
        /* ignore quota / private mode */
      }
      return { userProfile: next }
    }),

  /** Apply server chat fields to UI preferences for the active session */
  hydrateFromChat: (chat) => {
    if (!chat) return
    const personas = get().personas
    const personaId = chat.persona_id != null ? chat.persona_id : null
    set({
      selectedModel: chat.model ?? get().selectedModel,
      webSearchEnabled: Boolean(chat.web_search_enabled),
      activePersonaId: personaId,
      activeWorkspaceId: chat.workspace_id != null ? chat.workspace_id : null,
    })
    if (!personaId) {
      const def = defaultPersona(personas)
      set(personaToUi(def ?? null))
      return
    }
    const p = personas.find((x) => x.id === personaId)
    if (p) set(personaToUi(p))
  },
}))

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === USER_PROFILE_STORAGE_KEY) {
      useAppStore.getState().hydrateUserProfile()
    }
  })
}
