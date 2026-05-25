/**
 * API fetch helper. Auth is built-in (hlh_session cookie from POST /api/auth/login).
 * Optional: layer a reverse proxy (Authelia, oauth2-proxy) in front for defense in depth.
 * @param {string} path
 * @param {RequestInit & { json?: unknown }} options
 */
export async function apiFetch(path, options = {}) {
  const { json, headers: hdrs, ...rest } = options
  const headers = new Headers(hdrs)
  let body = rest.body
  if (json !== undefined) {
    headers.set('Content-Type', 'application/json')
    body = JSON.stringify(json)
  } else if (body instanceof FormData) {
    headers.delete('Content-Type')
  }
  const res = await fetch(path, { ...rest, headers, body })
  if (!res.ok) {
    if (res.status === 401) {
      throw new Error('Session expired')
    }
    const text = await res.text().catch(() => '')
    throw new Error(text || res.statusText || String(res.status))
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}

export async function getWorkspaceMemory(workspaceId) {
  return apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/memory`)
}

export async function addWorkspaceMemory(workspaceId, content) {
  return apiFetch(`/api/workspaces/${encodeURIComponent(workspaceId)}/memory`, {
    method: 'POST',
    json: { content },
  })
}

export async function deleteWorkspaceMemory(workspaceId, entryId) {
  return apiFetch(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/memory/${encodeURIComponent(entryId)}`,
    { method: 'DELETE' },
  )
}

export async function clearWorkspaceEmbeddings(workspaceId) {
  return apiFetch(`/api/sources/${encodeURIComponent(workspaceId)}/chunks`, {
    method: 'DELETE',
  })
}
