import { apiFetch } from '@/api/index.js'

export function getModelSettings() {
  return apiFetch('/api/inference/settings')
}

export function patchModelSettings(data) {
  return apiFetch('/api/inference/settings', { method: 'PATCH', json: data })
}
