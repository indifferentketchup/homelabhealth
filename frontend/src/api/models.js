import { apiFetch } from '@/api/index.js'

/** GET /api/models → { items: BundledModel[] }. */
export const listModels = () => apiFetch('/api/models')

/** GET /api/models/:id → single row detail. */
export const getModel = (id) => apiFetch(`/api/models/${encodeURIComponent(id)}`)

/** POST /api/models/:id/pull → 202 + row; backend queues an asyncio task. */
export const pullModel = (id) =>
  apiFetch(`/api/models/${encodeURIComponent(id)}/pull`, { method: 'POST' })

/** POST /api/models/pull-for-tier → 202 + { queued: [ids] }. */
export const pullForTier = (tier) =>
  apiFetch('/api/models/pull-for-tier', { method: 'POST', json: { tier } })

/** POST /api/models/:id/cancel → 200 + { ok, cancel_requested }. */
export const cancelPull = (id) =>
  apiFetch(`/api/models/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
