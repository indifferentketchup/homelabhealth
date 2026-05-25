import { apiFetch } from '@/api/index.js'

export const getModelServerConfig = () => apiFetch('/api/settings/inference')

export const patchModelServerConfig = (body) =>
  apiFetch('/api/settings/inference', { method: 'PATCH', json: body })

/** GET /api/settings/embedding → { provider_id, model, dimension } */
export const getEmbeddingSettings = () => apiFetch('/api/settings/embedding')

/**
 * PUT /api/settings/embedding
 * Body: { provider_id: uuid|null, model: string|null } — both null to disable.
 * Backend probes /v1/embeddings; rejects non-1024 dim with the verbatim
 * "embedding dimension mismatch: expected 1024, got <N>" string in detail.
 * apiFetch throws on 4xx/5xx; callers should catch and surface .message inline.
 */
export const putEmbeddingSettings = (body) =>
  apiFetch('/api/settings/embedding', { method: 'PUT', json: body })

/** GET /api/settings/reranker → { provider_id, model } */
export const getRerankerSettings = () => apiFetch('/api/settings/reranker')

/**
 * PUT /api/settings/reranker
 * Body: { provider_id: uuid|null, model: string|null } — both null = flashrank fallback.
 * No probe. Validation only.
 */
export const putRerankerSettings = (body) =>
  apiFetch('/api/settings/reranker', { method: 'PUT', json: body })

/** GET /api/settings/context-bar → { show_context_bar: boolean } */
export const getContextBarSetting = () => apiFetch('/api/settings/context-bar')

/** PUT /api/settings/context-bar — toggle the context usage indicator. */
export const putContextBarSetting = (show) =>
  apiFetch('/api/settings/context-bar', { method: 'PUT', json: { show_context_bar: show } })
