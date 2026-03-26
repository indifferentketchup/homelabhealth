import { apiFetch } from '@/api/index.js'

/**
 * @param {'booops' | '808notes'} mode
 */
export function fetchSearxngConfig(mode) {
  return apiFetch(`/api/searxng/${mode}`)
}

/**
 * @param {'booops' | '808notes'} mode
 * @param {{ safe_search: number, image_proxy: boolean, enabled_engines: string[], autocomplete: string }} config
 */
export function patchSearxngConfig(mode, config) {
  return apiFetch(`/api/searxng/${mode}`, { method: 'PATCH', json: config })
}
