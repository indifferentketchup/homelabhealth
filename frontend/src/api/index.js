export const BOOLAB_TOKEN_KEY = 'boolab_token'

const BOOLAB_TOKEN_MAX_AGE_SEC = 2592000 // 30 days

/** Shared across subdomains in production; omit on localhost (host-only cookie). */
export function getBoolabTokenCookieDomain() {
  const env = import.meta.env.VITE_AUTH_COOKIE_DOMAIN
  if (typeof env === 'string' && env.trim()) return env.trim()
  if (typeof window === 'undefined') return ''
  const h = window.location.hostname
  if (h === 'localhost' || h === '127.0.0.1' || h === '[::1]') return ''
  if (h === 'boogaardmusic.com' || h.endsWith('.boogaardmusic.com')) return '.boogaardmusic.com'
  return ''
}

function parseBoolabTokenFromCookie() {
  if (typeof document === 'undefined') return null
  const prefix = `${BOOLAB_TOKEN_KEY}=`
  const parts = document.cookie.split('; ')
  for (const p of parts) {
    if (p.startsWith(prefix)) {
      try {
        return decodeURIComponent(p.slice(prefix.length))
      } catch {
        return p.slice(prefix.length)
      }
    }
  }
  return null
}

/**
 * Cross-subdomain session: Http-accessible cookie with Path=/ and optional Domain=.boogaardmusic.com.
 * Migrates legacy per-origin `localStorage` token once when cookie is empty.
 */
export function getStoredBoolabToken() {
  if (typeof document === 'undefined') return null
  try {
    const fromCookie = parseBoolabTokenFromCookie()
    if (fromCookie) return fromCookie
    if (typeof localStorage === 'undefined') return null
    const legacy = localStorage.getItem(BOOLAB_TOKEN_KEY)
    if (legacy) {
      setBoolabTokenCookie(legacy)
      try {
        localStorage.removeItem(BOOLAB_TOKEN_KEY)
      } catch {
        /* ignore */
      }
      return legacy
    }
    return null
  } catch {
    return null
  }
}

export function setBoolabTokenCookie(token) {
  if (typeof document === 'undefined') return
  const domain = getBoolabTokenCookieDomain()
  const value = encodeURIComponent(token)
  const base = `${BOOLAB_TOKEN_KEY}=${value}; Path=/; Max-Age=${BOOLAB_TOKEN_MAX_AGE_SEC}; SameSite=Lax`
  document.cookie = domain ? `${base}; Domain=${domain}` : base
}

/** Clear host-only and domain cookies (covers domain + local dev). */
export function clearBoolabTokenCookie() {
  if (typeof document === 'undefined') return
  const expire = (domainPart) =>
    `${BOOLAB_TOKEN_KEY}=; Path=/; Max-Age=0; SameSite=Lax${domainPart ? `; Domain=${domainPart}` : ''}`
  document.cookie = expire('')
  const d = getBoolabTokenCookieDomain()
  if (d) document.cookie = expire(d)
  try {
    localStorage.removeItem(BOOLAB_TOKEN_KEY)
  } catch {
    /* ignore */
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

// DAW Memory (owner-only; callers should handle 403 for non-owners)
export async function getDawMemory(dawId) {
  return apiFetch(`/api/daws/${encodeURIComponent(dawId)}/memory`)
}

export async function addDawMemory(dawId, content) {
  return apiFetch(`/api/daws/${encodeURIComponent(dawId)}/memory`, {
    method: 'POST',
    json: { content },
  })
}

export async function deleteDawMemory(dawId, entryId) {
  return apiFetch(`/api/daws/${encodeURIComponent(dawId)}/memory/${encodeURIComponent(entryId)}`, {
    method: 'DELETE',
  })
}

