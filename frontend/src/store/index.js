import { create } from 'zustand'

export const useAppStore = create((set, get) => ({
  chats: [],
  setChats: (chats) => set({ chats: Array.isArray(chats) ? chats : [] }),

  activeChatId: null,
  setActiveChatId: (id) => set({ activeChatId: id }),

  messages: [],
  setMessages: (messages) => set({ messages: Array.isArray(messages) ? messages : [] }),

  selectedModel: null,
  setSelectedModel: (model) => set({ selectedModel: model }),

  webSearchEnabled: false,
  setWebSearchEnabled: (enabled) => set({ webSearchEnabled: Boolean(enabled) }),

  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: Boolean(open) }),

  /** Apply server chat fields to UI preferences for the active session */
  hydrateFromChat: (chat) => {
    if (!chat) return
    set({
      selectedModel: chat.model ?? get().selectedModel,
      webSearchEnabled: Boolean(chat.web_search_enabled),
    })
  },
}))
