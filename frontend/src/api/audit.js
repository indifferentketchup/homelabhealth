import { apiFetch } from '@/api/index.js'

/** GET /api/audit/refusals — safeguard event history, newest-first. */
export async function getRefusals({ limit = 50, offset = 0 } = {}) {
  return apiFetch(`/api/audit/refusals?limit=${limit}&offset=${offset}`)
}
