import { apiFetch } from './index.js'

export function listUsers() {
  return apiFetch('/api/users/')
}

export function createUser(username, password) {
  return apiFetch('/api/users/', { method: 'POST', json: { username, password } })
}

export function deleteUser(userId) {
  return apiFetch(`/api/users/${userId}`, { method: 'DELETE' })
}

export function adminSetUserPassword(userId, password) {
  return apiFetch(`/api/users/${userId}`, {
    method: 'PATCH',
    json: { password },
  })
}

/** User-level: change own password (members / super_admin). */
export function changeMyPassword(currentPassword, newPassword) {
  return apiFetch('/api/users/me/password', {
    method: 'PATCH',
    json: { current_password: currentPassword, new_password: newPassword },
  })
}
