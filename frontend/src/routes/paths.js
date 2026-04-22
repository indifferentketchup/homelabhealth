/** URL prefixes for multi-app routing on one host (e.g. dev without `VITE_APP_MODE`). */

const rawMode = import.meta.env.VITE_APP_MODE
const bakedMode =
  rawMode != null && String(rawMode).trim() !== ''
    ? String(rawMode).trim().toLowerCase()
    : null
const isBakedMode =
  bakedMode === 'booops' || bakedMode === '808notes' || bakedMode === 'boolab' || bakedMode === 'boocode'

/**
 * Legacy: one UI on one port with `/booops`, `/808notes`, `/boolab`.
 * Split Docker: bake `VITE_APP_MODE` — each service uses root paths only.
 */
export const USE_LEGACY_PATH_PREFIX = !isBakedMode

export const PATH_BOOLAB = USE_LEGACY_PATH_PREFIX ? '/boolab' : ''
export const PATH_BOOOPS = USE_LEGACY_PATH_PREFIX ? '/booops' : ''
export const PATH_808NOTES = USE_LEGACY_PATH_PREFIX ? '/808notes' : ''
export const PATH_BOOCODE = USE_LEGACY_PATH_PREFIX ? '/boocode' : ''

/** Safe home paths for `Link` / `navigate` (`''` would be invalid). */
export const PATH_BOOLAB_HOME = PATH_BOOLAB || '/'
export const PATH_BOOOPS_HOME = PATH_BOOOPS || '/'
export const PATH_808NOTES_HOME = PATH_808NOTES || '/'
export const PATH_BOOCODE_HOME = PATH_BOOCODE || '/'

/**
 * Hub link from BooOps / 808notes: full URL when split deploy, else path.
 * @returns {string}
 */
export function getBoolabHubHref() {
  const u = import.meta.env.VITE_PUBLIC_BOOLAB_URL
  if (typeof u === 'string' && u.trim()) return u.trim().replace(/\/$/, '')
  return PATH_BOOLAB_HOME
}

/** @returns {string | null} full URL when set (production / split) */
export function getBooopsPublicHref() {
  const u = import.meta.env.VITE_PUBLIC_BOOOPS_URL
  if (typeof u === 'string' && u.trim()) return u.trim().replace(/\/$/, '')
  return null
}

/** @returns {string | null} full URL when set (production / split) */
export function get808notesPublicHref() {
  const u = import.meta.env.VITE_PUBLIC_808NOTES_URL
  if (typeof u === 'string' && u.trim()) return u.trim().replace(/\/$/, '')
  return null
}

/** @returns {string | null} full URL when set (production / split) */
export function getBoocodePublicHref() {
  const u = import.meta.env.VITE_PUBLIC_BOOCODE_URL
  if (typeof u === 'string' && u.trim()) return u.trim().replace(/\/$/, '')
  return null
}

export function isHttpUrl(s) {
  return typeof s === 'string' && /^https?:\/\//i.test(s)
}

/**
 * 808notes DAW workspace paths (baked root `/daw/...` or legacy `/808notes/daw/...`).
 * @param {string} dawId
 * @param {'' | 'sources'} [suffix]
 */
export function notes808DawPath(dawId, suffix = '') {
  const id = String(dawId ?? '').replace(/^\/+|\/+$/g, '')
  if (!id) return PATH_808NOTES_HOME
  const tail = suffix === 'sources' ? `daw/${id}/sources` : `daw/${id}`
  const base = PATH_808NOTES.replace(/\/$/, '')
  if (!base) return `/${tail}`
  return `${base}/${tail}`
}

/**
 * BooCode DAW workspace path (baked root `/daw/:id` or legacy `/boocode/daw/:id`).
 * @param {string} dawId
 */
export function boocodeDawPath(dawId) {
  const id = String(dawId ?? '').replace(/^\/+|\/+$/g, '')
  if (!id) return PATH_BOOCODE_HOME
  const base = PATH_BOOCODE.replace(/\/$/, '')
  return base ? `${base}/daw/${id}` : `/daw/${id}`
}

/**
 * BooOps DAW chat path (baked root `/daw/:id` or legacy `/booops/daw/:id`).
 * @param {string} dawId
 */
export function booopsDawPath(dawId) {
  const id = String(dawId ?? '').replace(/^\/+|\/+$/g, '')
  if (!id) return PATH_BOOOPS_HOME
  const base = PATH_BOOOPS.replace(/\/$/, '')
  return base ? `${base}/daw/${id}` : `/daw/${id}`
}

/**
 * Mode from path prefix only (`/booops/...`, `/808notes/...`, `/boolab/...`, `/boocode/...`).
 * Does not treat `/` — use full `detectMode` for that.
 * @returns {'booops' | '808notes' | 'boolab' | 'boocode' | null}
 */
export function modeFromAppPath(pathname) {
  if (!USE_LEGACY_PATH_PREFIX) return null
  if (pathname == null || pathname === '') return null
  const p = pathname.startsWith('/') ? pathname : `/${pathname}`
  if (p === PATH_BOOOPS || p.startsWith(`${PATH_BOOOPS}/`)) return 'booops'
  if (p === PATH_808NOTES || p.startsWith(`${PATH_808NOTES}/`)) return '808notes'
  if (p === PATH_BOOCODE || p.startsWith(`${PATH_BOOCODE}/`)) return 'boocode'
  if (p === PATH_BOOLAB || p.startsWith(`${PATH_BOOLAB}/`)) return 'boolab'
  return null
}

/**
 * @param {string} pathname
 * @param {'booops' | '808notes' | 'boolab'} storeMode from `useAppStore`
 */
export function is808notesRouteContext(pathname, storeMode) {
  if (USE_LEGACY_PATH_PREFIX) {
    const p = pathname == null || pathname === '' ? '' : pathname.startsWith('/') ? pathname : `/${pathname}`
    return p === PATH_808NOTES || p.startsWith(`${PATH_808NOTES}/`)
  }
  return storeMode === '808notes'
}
