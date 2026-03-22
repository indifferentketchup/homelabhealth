/**
 * Subdomain → mode. Sets `data-mode` on <html> for CSS variables.
 * Exported `APP_MODE`: `booops` | `808notes` | `boolab`
 */
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

export function detectMode(hostname = window.location.hostname) {
  if (isLocalDevHost(hostname)) {
    return coerceAppMode(import.meta.env.VITE_APP_MODE || 'booops')
  }
  const forced = parseOptionalForcedMode()
  if (forced) return forced
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
