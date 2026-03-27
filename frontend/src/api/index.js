export const BOOLAB_TOKEN_KEY = 'boolab_token'

export function getStoredBoolabToken() {
  if (typeof localStorage === 'undefined') return null
  try {
    return localStorage.getItem(BOOLAB_TOKEN_KEY)
  } catch {
    return null
  }
}

/**
 * @param {string} path
 * @param {RequestInit & { json?: unknown }} options
 */
export async function apiFetch(path, options = {}) {
  const { json, headers: hdrs, ...rest } = options
  const headers = new Headers(hdrs)
  const token = getStoredBoolabToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  let body = rest.body
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(json)
  } else if (body instanceof FormData) {
    headers.delete('Content-Type')
  }
  const res = await fetch(path, { ...rest, headers, body })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || res.statusText || String(res.status))
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}
