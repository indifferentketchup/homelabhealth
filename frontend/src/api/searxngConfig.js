import { apiFetch } from '@/api/index.js'

export function fetchSearxngConfig() {
  return apiFetch('/api/searxng/')
}

/**
 * @param {{ safe_search: number, image_proxy: boolean, enabled_engines: string[], autocomplete: string }} config
 */
export function patchSearxngConfig(config) {
  return apiFetch('/api/searxng/', { method: 'PATCH', json: config })
}
