import { apiFetch } from '@/api/index.js'

export function fetchOllamaModels() {
  return apiFetch('/api/ollama/models')
}
