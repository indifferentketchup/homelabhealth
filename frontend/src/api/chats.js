import { apiFetch } from '@/api/index.js'

export function createChat(body = {}) {
  return apiFetch('/api/chats/', { method: 'POST', json: body })
}

export function listChats(params = {}) {
  const q = new URLSearchParams()
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  if (params.mode) q.set('mode', params.mode)
  if (params.dawId) q.set('daw_id', String(params.dawId))
  const qs = q.toString()
  const path = qs ? `/api/chats/?${qs}` : '/api/chats/'
  return apiFetch(path)
}

export function getChat(chatId) {
  return apiFetch(`/api/chats/${chatId}`)
}

export function patchChat(chatId, body) {
  return apiFetch(`/api/chats/${chatId}`, { method: 'PATCH', json: body })
}

/** Keep React Query recent list in sync when a chat title changes (manual or SSE). */
export function patchRecentChatsListCache(queryClient, chatId, title) {
  const id = String(chatId)
  queryClient.setQueriesData({ queryKey: ['chats', 'recent'] }, (old) => {
    if (!old?.items) return old
    let changed = false
    const items = old.items.map((c) => {
      if (String(c.id) !== id) return c
      changed = true
      return { ...c, title }
    })
    return changed ? { ...old, items } : old
  })
}

export function toggleWebSearch(chatId, enabled) {
  return apiFetch(`/api/chats/${chatId}/web-search`, { method: 'PATCH', json: { enabled } })
}

export function deleteChat(chatId) {
  return apiFetch(`/api/chats/${chatId}`, { method: 'DELETE' })
}

/** Delete all chats with no DAW attached (regular BooOps / 808notes chats only). */
export function deleteNonDawChats(mode = 'booops') {
  const q = new URLSearchParams({ mode })
  return apiFetch(`/api/chats/non-daw?${q}`, { method: 'DELETE' })
}

export function listMessages(chatId) {
  return apiFetch(`/api/chats/${chatId}/messages`)
}

export function forkChat(chatId, messageId) {
  return apiFetch(`/api/chats/${chatId}/messages/${messageId}/fork`, { method: 'POST' })
}

export function exportChat(id) {
  return apiFetch(`/api/chats/${encodeURIComponent(id)}/export`, { method: 'POST' })
}

export function getChatSourceSelection(chatId) {
  return apiFetch(`/api/chats/${chatId}/source-selection`)
}

export function setChatSourceSelection(chatId, sourceIds) {
  return apiFetch(`/api/chats/${chatId}/source-selection`, {
    method: 'PUT',
    json: { source_ids: sourceIds },
  })
}

