import { apiFetch } from '@/api/index.js'

export function createChat(body = {}) {
  return apiFetch('/api/chats/', { method: 'POST', json: body })
}

export function listChats(params = {}) {
  const q = new URLSearchParams()
  if (params.limit != null) q.set('limit', String(params.limit))
  if (params.offset != null) q.set('offset', String(params.offset))
  if (params.mode) q.set('mode', params.mode)
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

export function deleteChat(chatId) {
  return apiFetch(`/api/chats/${chatId}`, { method: 'DELETE' })
}

export function listMessages(chatId) {
  return apiFetch(`/api/chats/${chatId}/messages`)
}
