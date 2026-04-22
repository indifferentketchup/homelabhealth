import { apiFetch } from '@/api/index.js'

export const getRepoStatus = (dawId) =>
  apiFetch(`/api/boocode/daws/${encodeURIComponent(dawId)}/sync/status`)

export const listRepoTree = (dawId) =>
  apiFetch(`/api/boocode/daws/${encodeURIComponent(dawId)}/tree`)

export const getRepoStats = (dawId) =>
  apiFetch(`/api/boocode/daws/${encodeURIComponent(dawId)}/stats`)

export const getRepoFile = (dawId, path) =>
  apiFetch(
    `/api/boocode/daws/${encodeURIComponent(dawId)}/file?path=${encodeURIComponent(path)}`,
  )

export const listRepoSymbols = (dawId, path, line) => {
  const params = new URLSearchParams({ path })
  if (line != null) params.set('line', String(line))
  return apiFetch(
    `/api/boocode/daws/${encodeURIComponent(dawId)}/chunks?${params.toString()}`,
  )
}

export const listRepoBranches = (dawId) =>
  apiFetch(`/api/boocode/daws/${encodeURIComponent(dawId)}/branches`)

export const syncRepo = (dawId) =>
  apiFetch(`/api/boocode/daws/${encodeURIComponent(dawId)}/sync`, { method: 'POST' })

export const updateRepoConfig = (dawId, body) =>
  apiFetch(`/api/boocode/daws/${encodeURIComponent(dawId)}/repo`, {
    method: 'PATCH',
    json: body,
  })

export const repoSyncStreamUrl = (dawId) =>
  `/api/boocode/daws/${encodeURIComponent(dawId)}/sync/stream`
