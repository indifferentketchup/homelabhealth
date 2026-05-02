import { apiFetch } from '@/api/index.js'

export function getCustomInstructions() {
  return apiFetch('/api/custom-instructions/')
}

export function putCustomInstructions(content) {
  return apiFetch('/api/custom-instructions/', {
    method: 'PUT',
    json: { content },
  })
}
