import { apiFetch } from './index.js'

export async function login(username, password) {
  return apiFetch('/api/auth/login', {
    method: 'POST',
    json: { username, password },
  })
}

export async function fetchMe() {
  return apiFetch('/api/auth/me')
}

export async function patchProfile(body) {
  return apiFetch('/api/auth/profile', { method: 'PATCH', json: body })
}

export async function uploadProfileIcon(file) {
  const body = new FormData()
  body.append('file', file)
  return apiFetch('/api/auth/profile/icon', { method: 'POST', body })
}

export async function changePassword(currentPassword, newPassword) {
  return apiFetch('/api/auth/profile/password', {
    method: 'PATCH',
    json: { current_password: currentPassword, new_password: newPassword },
  })
}
