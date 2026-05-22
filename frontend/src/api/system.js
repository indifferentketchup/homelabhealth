import { apiFetch } from '@/api/index.js'

/** GET /api/system/hardware — live sysinfo collection, no DB write. */
export const getSystemHardware = () => apiFetch('/api/system/hardware')

/** GET /api/system/profile — { id, tier, tier_source, sysinfo_json, detected_at, chosen_at, setup_complete, recommended_tier }. */
export const getSystemProfile = () => apiFetch('/api/system/profile')

/**
 * PUT /api/system/profile
 * Body: { tier: string, tier_source: 'auto' | 'manual' }.
 * Sets chosen_at = NOW(), setup_complete = TRUE.
 */
export const putSystemProfile = (body) =>
  apiFetch('/api/system/profile', { method: 'PUT', json: body })

/** POST /api/system/redetect — re-run sysinfo + update detected_at. Does NOT change tier. */
export const postSystemRedetect = () =>
  apiFetch('/api/system/redetect', { method: 'POST' })

/** GET /api/system/hf-token — returns { configured: boolean, masked: string|null, updated_at: string|null }. */
export const getHfToken = () => apiFetch('/api/system/hf-token')

/**
 * PUT /api/system/hf-token — store or replace the HF token. Returns null (204).
 * @param {string} token
 */
export const putHfToken = (token) =>
  apiFetch('/api/system/hf-token', { method: 'PUT', json: { token } })

/** DELETE /api/system/hf-token — clear the stored HF token. Returns null (204). */
export const deleteHfToken = () =>
  apiFetch('/api/system/hf-token', { method: 'DELETE' })
