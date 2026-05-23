/** Single-mode app routes. Root paths only. */
// Route audit (v0.12.0 / C3): all paths are UUID-keyed. No PHI in URLs. Verified 2026-05-23.

export const PATH_HOME = '/'

export function workspacePath(workspaceId, suffix = '') {
  const id = String(workspaceId ?? '').replace(/^\/+|\/+$/g, '')
  if (!id) return PATH_HOME
  return suffix === 'sources' ? `/workspace/${id}/sources` : `/workspace/${id}`
}
