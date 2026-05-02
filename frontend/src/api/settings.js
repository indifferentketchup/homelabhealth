import { apiFetch } from '@/api/index.js'

export const getGlobalSettings = () => apiFetch('/api/settings/global')

export const patchGlobalSettings = (body) =>
  apiFetch('/api/settings/global', { method: 'PATCH', json: body })

export const getModelServerConfig = () => apiFetch('/api/settings/inference')

export const patchModelServerConfig = (body) =>
  apiFetch('/api/settings/inference', { method: 'PATCH', json: body })
