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

  selectedModel: null,
  setSelectedModel: (model) => set({ selectedModel: model }),

  /** Last known default from GET /api/inference/settings */
  defaultModel: null,
  setDefaultModel: (model) => set({ defaultModel: model ?? null }),

  webSearchEnabled: false,
  setWebSearchEnabled: (enabled) => set({ webSearchEnabled: Boolean(enabled) }),

  /** Optional default workspace (prompt context) for new chats */
  activeWorkspaceId: null,
  setActiveWorkspaceId: (id) => set({ activeWorkspaceId: id }),

  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: Boolean(open) }),

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
    set({
      selectedModel: chat.model ?? get().selectedModel,
      webSearchEnabled: Boolean(chat.web_search_enabled),
      activeWorkspaceId: chat.workspace_id != null ? chat.workspace_id : null,
    })
  },
}))

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === USER_PROFILE_STORAGE_KEY) {
      useAppStore.getState().hydrateUserProfile()
    }
  })
}
