import { apiFetch } from '@/api/index.js'

export function getMemory() {
  return apiFetch('/api/memory/')
}

export function putMemory(content) {
  return apiFetch('/api/memory/', {
    method: 'PUT',
    json: { content },
  })
}

export function extractMemory() {
  return apiFetch('/api/memory/extract', { method: 'POST' })
}

export function embedAllMemories() {
  return apiFetch('/api/memory/embed-all', { method: 'POST' })
}
