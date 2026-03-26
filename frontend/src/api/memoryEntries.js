import { apiFetch } from '@/api/index.js'

export function listMemoryEntries(mode = 'booops') {
  return apiFetch(`/api/memory/entries/?mode=${encodeURIComponent(mode)}`)
}

export function createMemoryEntry(content, mode = 'booops') {
  return apiFetch(`/api/memory/entries/?mode=${encodeURIComponent(mode)}`, {
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
