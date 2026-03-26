import { apiFetch } from '@/api/index.js'

export function getMemory(mode = 'booops') {
  return apiFetch(`/api/memory/?mode=${encodeURIComponent(mode)}`)
}

export function putMemory(mode, content) {
  return apiFetch(`/api/memory/?mode=${encodeURIComponent(mode)}`, {
    method: 'PUT',
    json: { content },
  })
}

export function extractMemory(mode = 'booops') {
  return apiFetch(`/api/memory/extract?mode=${encodeURIComponent(mode)}`, { method: 'POST' })
}
