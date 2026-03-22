/**
 * Subdomain → mode. Sets `data-mode` on <html> for CSS variables.
 * Exported `APP_MODE`: `booops` | `808notes` | `boolab`
 */
export function detectMode(hostname = window.location.hostname) {
  const forced = import.meta.env?.VITE_APP_MODE?.toLowerCase()
  if (forced === 'booops' || forced === '808notes' || forced === 'boolab') {
    return forced
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
