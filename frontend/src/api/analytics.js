import { apiFetch } from '@/api/index.js'

/**
 * GET /api/analytics/tokens
 * Returns { summary, sessions, models, providers } with aggregate token data.
 */
export async function getTokenAnalytics() {
  return apiFetch('/api/analytics/tokens')
}
