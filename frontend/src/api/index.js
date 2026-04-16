/**
 * Authelia handles auth upstream. No tokens, no cookies in-app.
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
    const text = await res.text().catch(() => '')
    throw new Error(text || res.statusText || String(res.status))
  }
  if (res.status === 204) return null
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return res.json()
  return res.text()
}

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

export async function clearDawEmbeddings(dawId) {
  return apiFetch(`/api/sources/${encodeURIComponent(dawId)}/chunks`, {
    method: 'DELETE',
  })
}
