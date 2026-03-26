import { apiFetch } from '@/api/index.js'

export function listPersonas(mode = 'booops') {
  return apiFetch(`/api/personas/?mode=${encodeURIComponent(mode)}`)
}

export function createPersona(body) {
  return apiFetch('/api/personas/', { method: 'POST', json: body })
}

export function getPersona(id) {
  return apiFetch(`/api/personas/${id}`)
}

export function updatePersona(id, body) {
  return apiFetch(`/api/personas/${id}`, { method: 'PUT', json: body })
}

export function deletePersona(id) {
  return apiFetch(`/api/personas/${id}`, { method: 'DELETE' })
}

export function uploadPersonaIcon(id, file) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/personas/${id}/icon`, { method: 'POST', body: fd })
}
