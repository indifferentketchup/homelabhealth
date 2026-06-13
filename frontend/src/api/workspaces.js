import { apiFetch } from '@/api/index.js'

export const listWorkspaces = () => apiFetch('/api/workspaces/')

export const getWorkspace = (id) => apiFetch(`/api/workspaces/${id}`)

export const createWorkspace = (body) => apiFetch('/api/workspaces/', { method: 'POST', json: body })

export const updateWorkspace = (id, body) =>
  apiFetch(`/api/workspaces/${id}`, { method: 'PATCH', json: body })

export const deleteWorkspace = (id) => apiFetch(`/api/workspaces/${id}`, { method: 'DELETE' })

export const pinWorkspace = (id, pinned) =>
  apiFetch(`/api/workspaces/${id}/pin`, { method: 'PATCH', json: { pinned } })

export const uploadWorkspaceIcon = (id, file) => {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/workspaces/${id}/icon`, { method: 'POST', body: fd })
}

export const getWorkspaceInstructions = (id) =>
  apiFetch(`/api/workspaces/${id}/instructions`)

export const putWorkspaceInstructions = (id, content) =>
  apiFetch(`/api/workspaces/${id}/instructions`, { method: 'PUT', json: { content } })

export const listContextFiles = (workspaceId) =>
  apiFetch(`/api/workspace-context-files/?workspace_id=${encodeURIComponent(workspaceId)}`)

export const uploadContextFile = (workspaceId, file, embeddable = false) => {
  const fd = new FormData()
  fd.append('workspace_id', workspaceId)
  fd.append('file', file)
  fd.append('embeddable', String(embeddable))
  return apiFetch('/api/workspace-context-files/', { method: 'POST', body: fd })
}

export const deleteContextFile = (id) =>
  apiFetch(`/api/workspace-context-files/${id}`, { method: 'DELETE' })

export const patchContextFile = (id, body) =>
  apiFetch(`/api/workspace-context-files/${id}`, { method: 'PATCH', json: body })

export const loadDemo = () => apiFetch('/api/demo/load', { method: 'POST' })
