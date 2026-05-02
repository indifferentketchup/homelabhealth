import { apiFetch } from '@/api/index.js'

export function fetchModels() {
  return apiFetch('/api/inference/models')
}

export function getModelSettings() {
  return apiFetch('/api/inference/settings')
}

export function patchModelSettings(data) {
  return apiFetch('/api/inference/settings', { method: 'PATCH', json: data })
}
