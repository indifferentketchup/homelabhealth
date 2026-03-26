/**
 * Mode from URL path (legacy single-host only), query, host, or baked `VITE_APP_MODE`.
 * Sets `data-mode` on `<html>`.
 * Exported `APP_MODE`: `booops` | `808notes` | `boolab`
 */
import { modeFromAppPath } from './routes/paths.js'

const IPV4_RE = /^\d+\.\d+\.\d+\.\d+$/

function isLocalDevHost(hostname) {
  if (!hostname) return true
  const h = String(hostname).toLowerCase()
  if (h === 'localhost') return true
  return IPV4_RE.test(String(hostname))
}

function coerceAppMode(raw) {
  const v =
    raw == null || String(raw).trim() === ''
      ? 'booops'
      : String(raw).trim().toLowerCase()
  if (v === 'booops' || v === '808notes' || v === 'boolab') return v
  return 'booops'
}

function parseOptionalForcedMode() {
  const raw = import.meta.env.VITE_APP_MODE
  if (raw == null || String(raw).trim() === '') return null
  const v = String(raw).trim().toLowerCase()
  if (v === 'booops' || v === '808notes' || v === 'boolab') return v
  return null
}

/** e.g. `?mode=808notes` */
function parseModeQuery(search) {
  if (typeof search !== 'string' || !search) return null
  try {
    const q = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search).get('mode')
    if (q == null || String(q).trim() === '') return null
    const v = String(q).trim().toLowerCase()
    if (v === 'booops' || v === '808notes' || v === 'boolab') return v
  } catch {
    /* ignore */
  }
  return null
}

export function detectMode(
  hostname = window.location.hostname,
  search = window.location.search,
  pathname = window.location.pathname,
) {
  const pathMode = modeFromAppPath(pathname)
  if (pathMode != null) return pathMode

  const fromQuery = parseModeQuery(search)
  if (fromQuery) return fromQuery

  const baked = parseOptionalForcedMode()
  if (baked != null) return baked

  if (pathname === '/' || pathname === '') {
    if (!isLocalDevHost(hostname)) {
      const head = hostname.split('.')[0]?.toLowerCase() ?? ''
      if (head === '808notes') return '808notes'
      if (head === 'booops') return 'booops'
      if (head === 'boolab') return 'boolab'
    }
    return 'boolab'
  }

  if (isLocalDevHost(hostname)) {
    return coerceAppMode(import.meta.env.VITE_APP_MODE || 'booops')
  }
  const head = hostname.split('.')[0]?.toLowerCase() ?? ''
  if (head === '808notes') return '808notes'
  if (head === 'booops') return 'booops'
  if (head === 'boolab') return 'boolab'
  return 'boolab'
}

export function applyMode(mode) {
  const root = document.documentElement
  root.setAttribute('data-mode', mode)
  root.classList.add('dark')
}

export const APP_MODE = detectMode()
applyMode(APP_MODE)
