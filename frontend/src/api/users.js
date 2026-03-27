import { apiFetch } from './index.js'

export function listUsers() {
  return apiFetch('/api/users/')
}

export function adminSetUserPassword(userId, password) {
  return apiFetch(`/api/users/${userId}`, {
    method: 'PATCH',
    json: { password },
  })
}
