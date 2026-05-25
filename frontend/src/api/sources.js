import { apiFetch } from '@/api/index.js'

export function uploadSources(files, workspaceId) {
  const fd = new FormData()
  for (const file of files) {
    fd.append('files', file)
  }
  return apiFetch(`/api/sources/${workspaceId}/upload`, { method: 'POST', body: fd })
}

export const uploadSource = (file, workspaceId) => uploadSources([file], workspaceId)

export function listSources(workspaceId) {
  return apiFetch(`/api/sources/${workspaceId}`)
}

export function deleteSource(sourceId) {
  return apiFetch(`/api/sources/by-id/${sourceId}`, { method: 'DELETE' })
}
