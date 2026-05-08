/** Single-mode app routes. Root paths only. */

export const PATH_HOME = '/'

export function workspacePath(workspaceId, suffix = '') {
  const id = String(workspaceId ?? '').replace(/^\/+|\/+$/g, '')
  if (!id) return PATH_HOME
  return suffix === 'sources' ? `/workspace/${id}/sources` : `/workspace/${id}`
}
