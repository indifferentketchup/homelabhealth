import { apiFetch } from '@/api/index.js'

export const getModelServerConfig = () => apiFetch('/api/settings/inference')

export const patchModelServerConfig = (body) =>
  apiFetch('/api/settings/inference', { method: 'PATCH', json: body })
