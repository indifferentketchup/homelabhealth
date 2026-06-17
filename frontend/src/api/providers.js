import { apiFetch } from '@/api/index.js'

/** GET /api/providers  -  returns { items: Provider[] }. api_key is always "***" or null. */
export function listProviders() {
  return apiFetch('/api/providers')
}

export function getProvider(id) {
  return apiFetch(`/api/providers/${encodeURIComponent(id)}`)
}

/**
 * POST /api/providers
 * @param {{name: string, base_url: string, api_key?: string|null, enabled?: boolean, sort_order?: number}} body
 */
export function createProvider(body) {
  return apiFetch('/api/providers', { method: 'POST', json: body })
}

/**
 * PATCH /api/providers/:id  -  caller MUST omit `api_key` to preserve current value.
 * Send `api_key: null` to clear. Send `api_key: "<value>"` to replace.
 * (Empty string is rejected by the backend.)
 */
export function patchProvider(id, body) {
  return apiFetch(`/api/providers/${encodeURIComponent(id)}`, { method: 'PATCH', json: body })
}

/**
 * DELETE /api/providers/:id?force=...
 * Uses raw fetch so we can read the 409 dependency-counts body without throwing.
 * @returns {Promise<{ ok: true } | { ok: false, status: 409, references: { workspaces: number, embedding: boolean, reranker: boolean } }>}
 */
export async function deleteProvider(id, { force = false } = {}) {
  const url = `/api/providers/${encodeURIComponent(id)}${force ? '?force=true' : ''}`
  const res = await fetch(url, { method: 'DELETE' })
  if (res.status === 204) return { ok: true }
  if (res.status === 409) {
    let body = null
    try {
      body = await res.json()
    } catch {
      /* malformed body shouldn't happen, but don't blow up */
    }
    const detail = body?.detail
    // FastAPI wraps the dict in { detail: {...} }. Our 409 payload puts
    // references inside detail, so unwrap one layer.
    const refs = (detail && typeof detail === 'object' && 'references' in detail)
      ? detail.references
      : (body?.references ?? null)
    return {
      ok: false,
      status: 409,
      references: refs || { workspaces: 0, embedding: false, reranker: false },
    }
  }
  const text = await res.text().catch(() => '')
  throw new Error(text || res.statusText || String(res.status))
}

/** POST /api/providers/:id/test  -  always returns HTTP 200; outcome lives in { ok, status, models? }. */
export function testProvider(id) {
  return apiFetch(`/api/providers/${encodeURIComponent(id)}/test`, { method: 'POST' })
}

/** GET /api/providers/:id/models  -  proxies the upstream /v1/models response. */
export function listProviderModels(id) {
  return apiFetch(`/api/providers/${encodeURIComponent(id)}/models`)
}
