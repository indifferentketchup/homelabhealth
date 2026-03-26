import { apiFetch } from '@/api/index.js'

export const getGlobalSettings = () => apiFetch('/api/settings/global')

export const patchGlobalSettings = (body) =>
  apiFetch('/api/settings/global', { method: 'PATCH', json: body })

export const getOllamaConfig = () => apiFetch('/api/settings/ollama')

export const patchOllamaConfig = (body) =>
  apiFetch('/api/settings/ollama', { method: 'PATCH', json: body })
