import { apiFetch } from '@/api/index.js'

export function listNotes(workspaceId) {
  return apiFetch(`/api/notes/${workspaceId}`)
}

export function createNote(workspaceId, body) {
  return apiFetch(`/api/notes/${workspaceId}`, { method: 'POST', json: body })
}

export function updateNote(noteId, body) {
  return apiFetch(`/api/notes/${noteId}`, { method: 'PUT', json: body })
}

export function deleteNote(noteId) {
  return apiFetch(`/api/notes/${noteId}`, { method: 'DELETE' })
}
