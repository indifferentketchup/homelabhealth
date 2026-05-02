import { apiFetch } from '@/api/index.js'

export function listMemoryEntries() {
  return apiFetch('/api/memory/entries/')
}

export function createMemoryEntry(content) {
  return apiFetch('/api/memory/entries/', {
    method: 'POST',
    json: { content, source: 'manual' },
  })
}

export function updateMemoryEntry(id, content) {
  return apiFetch(`/api/memory/entries/${id}`, { method: 'PATCH', json: { content } })
}

export function deleteMemoryEntry(id) {
  return apiFetch(`/api/memory/entries/${id}`, { method: 'DELETE' })
}
