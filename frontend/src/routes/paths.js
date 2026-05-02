/** Single-mode app routes. Root paths only. */

export const PATH_HOME = '/'

/** @returns {string | null} full URL when set (production / split build) */
export function getPublicHref() {
  const u = import.meta.env.VITE_PUBLIC_808NOTES_URL || import.meta.env.VITE_PUBLIC_URL
  if (typeof u === 'string' && u.trim()) return u.trim().replace(/\/$/, '')
  return null
}

export function isHttpUrl(s) {
  return typeof s === 'string' && /^https?:\/\//i.test(s)
}

export function workspacePath(workspaceId, suffix = '') {
  const id = String(workspaceId ?? '').replace(/^\/+|\/+$/g, '')
  if (!id) return PATH_HOME
  return suffix === 'sources' ? `/workspace/${id}/sources` : `/workspace/${id}`
}
