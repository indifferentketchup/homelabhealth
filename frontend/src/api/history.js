import { apiFetch } from './index.js'

// history management (list/view/rename/delete)
export async function listHistory(kind, { dawId }) {
  const qs = new URLSearchParams({ daw_id: dawId })
  return apiFetch(`/api/history/${kind}?${qs.toString()}`)
}

export async function readHistory(kind, { dawId, file }) {
  const qs = new URLSearchParams({ daw_id: dawId, file })
  return apiFetch(`/api/history/${kind}/content?${qs.toString()}`)
}

export async function renameHistory(kind, { dawId, oldName, newName }) {
  // newName can be "__ai__" to trigger AI rename
  return apiFetch(`/api/history/${kind}/rename`, {
    method: 'POST',
    json: { daw_id: dawId, old: oldName, new: newName },
  })
}

export async function deleteHistory(kind, { dawId, file }) {
  return apiFetch(`/api/history/${kind}`, {
    method: 'DELETE',
    json: { daw_id: dawId, file },
  })
}
