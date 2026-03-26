import { apiFetch } from '@/api/index.js'

/** Platform default when API/settings omit a model (aligned with backend `DEFAULT_MODEL`). */
export const DEFAULT_OLLAMA_MODEL = 'qwen3.5:9b'

export function fetchOllamaModels() {
  return apiFetch('/api/ollama/models')
}

/** @param {string} [mode] booops | 808notes */
export function getOllamaSettings(mode = 'booops') {
  const m = mode === '808notes' ? '808notes' : 'booops'
  return apiFetch(`/api/ollama/settings?mode=${encodeURIComponent(m)}`)
}

/** @param {string} [mode] booops | 808notes */
export function patchOllamaSettings(data, mode = 'booops') {
  const m = mode === '808notes' ? '808notes' : 'booops'
  return apiFetch(`/api/ollama/settings?mode=${encodeURIComponent(m)}`, { method: 'PATCH', json: data })
}

/** URL for POST SSE pull (body: `{ model }`). */
export const pullModel = (_model) => '/api/ollama/pull'

export const deleteModel = (model) =>
  apiFetch(`/api/ollama/models/${encodeURIComponent(model)}`, { method: 'DELETE' })

export const unloadAllModels = () => apiFetch('/api/ollama/unload-all', { method: 'POST' })
