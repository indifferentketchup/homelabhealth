import { create } from 'zustand'

import { fetchMe } from '@/api/auth.js'
import {
  clearBoolabTokenCookie,
  getStoredBoolabToken,
  setBoolabTokenCookie,
} from '@/api/index.js'
import { APP_MODE } from '../mode.js'

const USER_PROFILE_STORAGE_KEY = 'boolab-user-profile-v1'
const USER_PROFILE_LEGACY_STORAGE_KEY = 'booops-user-profile-v1'

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
    let json = localStorage.getItem(USER_PROFILE_STORAGE_KEY)
    if (!json) json = localStorage.getItem(USER_PROFILE_LEGACY_STORAGE_KEY)
    if (!json) return normalizeUserProfile(null)
    return normalizeUserProfile(JSON.parse(json))
  } catch {
    return normalizeUserProfile(null)
  }
}

/** Active default for the given app (or BooOps when mode is boolab / unknown). */
export function defaultPersonaForAppMode(personas, appMode) {
  const list = Array.isArray(personas) ? personas : []
  if (appMode === '808notes') return list.find((x) => x.is_default_808notes) ?? null
  return list.find((x) => x.is_default_booops) ?? null
}

/** Map API persona row → store display fields (also used after AI settings refetch). */
export function personaFieldsFromRecord(p) {
  if (!p) {
    return {
      personaDisplayName: 'BooOps',
      personaIconUrl: null,
      personaEmoji: '🤖',
    }
  }
  return {
    personaDisplayName: (p.name && String(p.name).trim()) || 'BooOps',
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
  /** Resolved from URL path / query / host (see `mode.js`, `ModeSync`). */
  mode: APP_MODE,

  token: typeof window !== 'undefined' ? getStoredBoolabToken() : null,
  currentUser: null,
  /** Authenticated fetch of `/api/auth/profile/icon-asset` as blob URL (DB accounts only). */
  profileIconObjectUrl: null,
  setToken: (token) => {
    try {
      if (token) setBoolabTokenCookie(token)
      else clearBoolabTokenCookie()
    } catch {
      /* ignore */
    }
    set({ token: token || null })
  },
  clearToken: () => {
    try {
      clearBoolabTokenCookie()
    } catch {
      /* ignore */
    }
    revokeProfileIconObjectUrl(get().profileIconObjectUrl)
    set({ token: null, currentUser: null, profileIconObjectUrl: null })
  },
  setCurrentUser: (user) => set({ currentUser: user }),
  syncUserProfileFromServer: async (me) => {
    if (!me || me.role === 'owner') {
      revokeProfileIconObjectUrl(get().profileIconObjectUrl)
      if (me?.role === 'owner') set({ profileIconObjectUrl: null })
      return
    }
    revokeProfileIconObjectUrl(get().profileIconObjectUrl)
    let profileIconObjectUrl = null
    const token = getStoredBoolabToken()
    if (me.icon_url && token) {
      try {
        const res = await fetch('/api/auth/profile/icon-asset', {
          headers: { Authorization: `Bearer ${token}` },
        })
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
      localStorage.removeItem(USER_PROFILE_LEGACY_STORAGE_KEY)
    } catch {
      /* ignore */
    }
    set({ userProfile, profileIconObjectUrl })
  },
  bootstrapAuth: async () => {
    const t = get().token
    if (!t) {
      set({ currentUser: null })
      return
    }
    try {
      const me = await fetchMe()
      set({ currentUser: me })
      if (me.role === 'owner') {
        revokeProfileIconObjectUrl(get().profileIconObjectUrl)
        set({ profileIconObjectUrl: null })
      } else {
        await get().syncUserProfileFromServer(me)
      }
    } catch {
      get().clearToken()
    }
  },
  setMode: (mode) =>
    set({
      mode:
        mode === 'booops' || mode === '808notes' || mode === 'boolab' ? mode : 'boolab',
    }),

  chats: [],
  setChats: (chats) => set({ chats: Array.isArray(chats) ? chats : [] }),

  activeChatId: null,
  setActiveChatId: (id) => set({ activeChatId: id }),

  messages: [],
  setMessages: (messages) => set({ messages: Array.isArray(messages) ? messages : [] }),

  selectedModel: null,
  setSelectedModel: (model) => set({ selectedModel: model }),

  /** Last known default from GET /api/ollama/settings */
  defaultModel: null,
  setDefaultModel: (model) => set({ defaultModel: model ?? null }),

  webSearchEnabled: false,
  setWebSearchEnabled: (enabled) => set({ webSearchEnabled: Boolean(enabled) }),

  personaDisplayName: 'BooOps',
  personaIconUrl: null,
  personaEmoji: '🤖',
  setPersonaIconUrl: (url) => set({ personaIconUrl: url ?? null }),
  setPersonaEmoji: (emoji) => set({ personaEmoji: emoji || '🤖' }),

  /** Default persona for new chats (initialized from API default) */
  activePersonaId: null,
  setActivePersonaId: (id) =>
    set((s) => {
      if (!id) {
        const def = defaultPersonaForAppMode(s.personas, s.mode)
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
        const def = defaultPersonaForAppMode(personas, s.mode)
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

  /** Optional default DAW (prompt context) for new chats */
  activeDawId: null,
  setActiveDawId: (id) => set({ activeDawId: id }),

  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: Boolean(open) }),

  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: Boolean(open) }),

  /** Merged BooOps branding (for layout tokens e.g. sidebar width); updated when CSS is applied */
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
        try {
          localStorage.removeItem(USER_PROFILE_LEGACY_STORAGE_KEY)
        } catch {
          /* ignore */
        }
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
      activeDawId: chat.daw_id != null ? chat.daw_id : null,
    })
    if (!personaId) {
      const def = defaultPersonaForAppMode(personas, get().mode)
      set(personaToUi(def ?? null))
      return
    }
    const p = personas.find((x) => x.id === personaId)
    if (p) set(personaToUi(p))
  },
}))

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (
      e.key === USER_PROFILE_STORAGE_KEY ||
      e.key === USER_PROFILE_LEGACY_STORAGE_KEY
    ) {
      useAppStore.getState().hydrateUserProfile()
    }
  })
}
