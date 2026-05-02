import { apiFetch } from '@/api/index.js'

export function uploadSource(file, workspaceId) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/sources/${workspaceId}/upload`, { method: 'POST', body: fd })
}

export function listSources(workspaceId) {
  return apiFetch(`/api/sources/${workspaceId}`)
}

export function deleteSource(sourceId) {
  return apiFetch(`/api/sources/by-id/${sourceId}`, { method: 'DELETE' })
}
