import { apiFetch } from '@/api/index.js'

export const listDaws = (mode) => {
  const q = mode != null && mode !== '' ? `?mode=${encodeURIComponent(mode)}` : ''
  return apiFetch(`/api/daws/${q}`)
}

export const getDaw = (id) => apiFetch(`/api/daws/${id}`)

export const createDaw = (body) => apiFetch('/api/daws/', { method: 'POST', json: body })

export const updateDaw = (id, body) => apiFetch(`/api/daws/${id}`, { method: 'PATCH', json: body })

export const deleteDaw = (id) => apiFetch(`/api/daws/${id}`, { method: 'DELETE' })

export const pinDaw = (id, slot, pinned) =>
  apiFetch(`/api/daws/${id}/pin`, { method: 'PATCH', json: { slot, pinned } })

export const uploadDawIcon = (id, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/daws/${id}/icon`, { method: 'POST', body: fd })
}

export const getDawInstructions = (id) => apiFetch(`/api/daws/${id}/instructions`)

export const putDawInstructions = (id, content) =>
  apiFetch(`/api/daws/${id}/instructions`, { method: 'PUT', json: { content } })

export const listContextFiles = (dawId) =>
  apiFetch(`/api/daw-context-files/?daw_id=${encodeURIComponent(dawId)}`)

export const uploadContextFile = (dawId, file, embeddable = false) => {
  const fd = new FormData()
  fd.append('daw_id', dawId)
  fd.append('file', file)
  fd.append('embeddable', String(embeddable))
  return apiFetch('/api/daw-context-files/', { method: 'POST', body: fd })
}

export const deleteContextFile = (id) => apiFetch(`/api/daw-context-files/${id}`, { method: 'DELETE' })

export const patchContextFile = (id, body) =>
  apiFetch(`/api/daw-context-files/${id}`, { method: 'PATCH', json: body })
