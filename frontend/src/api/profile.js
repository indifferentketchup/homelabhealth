import { apiFetch } from './index.js'

export async function fetchMe() {
  return apiFetch('/api/profile/me')
}

export async function patchProfile(body) {
  return apiFetch('/api/profile/', { method: 'PATCH', json: body })
}

export async function uploadProfileIcon(file) {
  const body = new FormData()
  body.append('file', file)
  return apiFetch('/api/profile/icon', { method: 'POST', body })
}
