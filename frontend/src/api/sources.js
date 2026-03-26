import { apiFetch } from '@/api/index.js'

export function uploadSource(file, dawId) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/sources/${dawId}/upload`, { method: 'POST', body: fd })
}

export function listSources(dawId) {
  return apiFetch(`/api/sources/${dawId}`)
}

export function deleteSource(sourceId) {
  return apiFetch(`/api/sources/by-id/${sourceId}`, { method: 'DELETE' })
}
