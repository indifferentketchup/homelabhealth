import { apiFetch } from '@/api/index.js'

export function listNotes(dawId) {
  return apiFetch(`/api/notes/${dawId}`)
}

export function createNote(dawId, body) {
  return apiFetch(`/api/notes/${dawId}`, { method: 'POST', json: body })
}

export function updateNote(noteId, body) {
  return apiFetch(`/api/notes/${noteId}`, { method: 'PUT', json: body })
}

export function deleteNote(noteId) {
  return apiFetch(`/api/notes/${noteId}`, { method: 'DELETE' })
}
