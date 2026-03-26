import { apiFetch } from '@/api/index.js'

export function getCustomInstructions(scope) {
  return apiFetch(`/api/custom-instructions/?scope=${encodeURIComponent(scope)}`)
}

export function putCustomInstructions(scope, content) {
  return apiFetch(`/api/custom-instructions/?scope=${encodeURIComponent(scope)}`, {
    method: 'PUT',
    json: { content },
  })
}
