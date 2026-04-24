import { apiFetch } from '@/api/index.js'

export const listMachines = () =>
  apiFetch('/api/terminals/machines')

export const list = ({ dawId } = {}) => {
  const qs = dawId ? `?daw_id=${encodeURIComponent(dawId)}` : ''
  return apiFetch(`/api/terminals${qs}`)
}

export const create = ({ machineId, dawId, label, startingCmd, cwd }) =>
  apiFetch('/api/terminals', {
    method: 'POST',
    json: {
      machine_id: machineId,
      daw_id: dawId ?? null,
      label: label ?? null,
      starting_cmd: startingCmd ?? null,
      cwd: cwd ?? null,
    },
  })

export const del = (id) =>
  apiFetch(`/api/terminals/${encodeURIComponent(id)}`, { method: 'DELETE' })

export const exportTerminal = (id) =>
  apiFetch(`/api/terminals/${encodeURIComponent(id)}/export`, { method: 'POST' })

export const patch = (id, body) =>
  apiFetch(`/api/terminals/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    json: body,
  })

export const paste = (id, text, appendNewline = false) =>
  apiFetch(`/api/terminals/${encodeURIComponent(id)}/paste`, {
    method: 'POST',
    json: { text, append_newline: appendNewline },
  })

// Cookie-based auth (Authelia forward_auth on the vhost); token never in URL.
// Derives wss://host/ws/terminals/:id from same-origin to keep the cookie scope.
export const wsUrl = (id) => {
  const loc = typeof window !== 'undefined' ? window.location : null
  const proto = loc && loc.protocol === 'https:' ? 'wss' : 'ws'
  const host = loc ? loc.host : ''
  return `${proto}://${host}/ws/terminals/${encodeURIComponent(id)}`
}
