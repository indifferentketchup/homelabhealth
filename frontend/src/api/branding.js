import { apiFetch } from '@/api/index.js'
import { applyWorkspaceLayoutToDom } from '@/lib/workspaceLayout.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

/** Short name → full CSS `font-family` stack (Google Fonts). */
export const FONT_BODY_STACKS = {
  Rajdhani: "'Rajdhani', sans-serif",
  'Space Grotesk': "'Space Grotesk', sans-serif",
  Inter: "'Inter', sans-serif",
  'Exo 2': "'Exo 2', sans-serif",
  'DM Sans': "'DM Sans', sans-serif",
  Oxanium: "'Oxanium', sans-serif",
  'JetBrains Mono': "'JetBrains Mono', monospace",
  'Google Sans Code': "'Google Sans Code', monospace",
}

export const FONT_MONO_STACKS = {
  'Fira Code': "'Fira Code', monospace",
  'JetBrains Mono': "'JetBrains Mono', monospace",
  'Share Tech Mono': "'Share Tech Mono', monospace",
  'Ubuntu Sans Mono': "'Ubuntu Sans Mono', monospace",
  'Google Sans Code': "'Google Sans Code', monospace",
}

export const FONT_BODY_OPTIONS = Object.keys(FONT_BODY_STACKS)
export const FONT_MONO_OPTIONS = Object.keys(FONT_MONO_STACKS)

function inferFontBodyFromFamily(ff) {
  if (typeof ff !== 'string') return 'Rajdhani'
  if (ff.includes('Space Grotesk') || (ff.includes('Space') && ff.includes('Grotesk'))) return 'Space Grotesk'
  if (ff.includes('Google Sans Code')) return 'Google Sans Code'
  if (ff.includes('JetBrains Mono')) return 'JetBrains Mono'
  for (const name of FONT_BODY_OPTIONS) {
    if (name === 'Space Grotesk') continue
    if (ff.includes(name)) return name
  }
  return 'Rajdhani'
}

export function resolveBodyFontStack(config) {
  const merged = patchBranding(null, config)
  return FONT_BODY_STACKS[merged.fontBody] || FONT_BODY_STACKS.Rajdhani
}

export function resolveMonoFontStack(config) {
  const merged = patchBranding(null, config)
  return FONT_MONO_STACKS[merged.fontMono] || FONT_MONO_STACKS['Fira Code']
}

/** Default workspace branding (aligned with API `/api/branding/`). */
export const DEFAULT_BRANDING = {
  accentColor: '#7c3aed',
  accentCyan: '#c084fc',
  accentPurple: '#e879f9',
  bgColor: '#080808',
  bgPanel: '#0f0a1a',
  bgCard: '#130d20',
  textColor: '#f0f0f0',
  textDim: '#9d8fbb',
  borderColor: '#1e1530',
  fontFamily: 'Rajdhani, sans-serif',
  fontSizeBase: 15,
  baseFontSize: 15,
  fsNav: 13,
  fsChat: 15,
  fsInput: 14,
  fsHeading: 18,
  fsCode: 13,
  chatMaxWidth: 850,
  sidebarWidth: 280,
  title: 'Workspace',
  /** Landing hero line under the title (editable in Settings -> Branding). */
  subtitle: '// pick your desk. open a workspace.',
  bannerUrl: '',
  logoUrl: '',
  faviconUrl: '',
  appGlyphIcon: 'Music2',
}

function finalizeBranding(merged, defaults) {
  const fsb = merged.fontSizeBase ?? merged.baseFontSize ?? defaults.fontSizeBase
  const bfs = merged.baseFontSize ?? merged.fontSizeBase ?? defaults.baseFontSize
  let fontBody = merged.fontBody
  if (!fontBody || !FONT_BODY_STACKS[fontBody]) {
    fontBody = inferFontBodyFromFamily(merged.fontFamily)
  }
  let fontMono = merged.fontMono
  if (!fontMono || !FONT_MONO_STACKS[fontMono]) {
    fontMono = 'Fira Code'
  }
  return { ...merged, fontSizeBase: fsb, baseFontSize: bfs, fontBody, fontMono }
}

function mergeBrandingDefaults(defaults, base, partial) {
  const merged = {
    ...defaults,
    ...(base && typeof base === 'object' ? base : {}),
    ...(partial && typeof partial === 'object' ? partial : {}),
  }
  return finalizeBranding(merged, defaults)
}

/** Merge defaults + stored + optional patch (client preview). */
export function patchBranding(base, partial) {
  const merged = {
    ...DEFAULT_BRANDING,
    ...(base && typeof base === 'object' ? base : {}),
    ...(partial && typeof partial === 'object' ? partial : {}),
  }
  // DB/API may store null; spread would otherwise wipe defaults and empty the landing tagline.
  if (merged.title == null) merged.title = DEFAULT_BRANDING.title
  if (merged.subtitle == null) merged.subtitle = DEFAULT_BRANDING.subtitle
  return finalizeBranding(merged, DEFAULT_BRANDING)
}

function clampFs(n, lo = 10, hi = 24) {
  if (!Number.isFinite(n)) return null
  return Math.min(hi, Math.max(lo, Math.round(n)))
}

function fsToPx(v, fallback) {
  const n = typeof v === 'number' ? v : Number(v)
  const c = clampFs(n) ?? clampFs(fallback) ?? fallback
  return `${c}px`
}

/**
 * Apply branding tokens to the document root (live preview).
 * @param {object} config Merged branding (+ layout) fields.
 */
export function applyBrandingCss(config) {
  const root = document.documentElement
  const defaults = DEFAULT_BRANDING
  const merged = mergeBrandingDefaults(defaults, config, null)

  const px = (n) => (typeof n === 'number' && Number.isFinite(n) ? `${Math.round(n)}px` : null)
  const set = (prop, value) => {
    if (value != null && value !== '') root.style.setProperty(prop, String(value))
  }

  set('--accent', merged.accentColor)
  set('--accent-2', merged.accentCyan)
  set('--accent-3', merged.accentPurple)
  set('--bg', merged.bgColor)
  set('--background', merged.bgColor)
  set('--bg-panel', merged.bgPanel)
  set('--popover', merged.bgPanel)
  set('--muted', merged.bgPanel)
  set('--bg-card', merged.bgCard)
  set('--card', merged.bgCard)
  set('--text', merged.textColor)
  set('--foreground', merged.textColor)
  set('--card-foreground', merged.textColor)
  set('--popover-foreground', merged.textColor)
  set('--text-dim', merged.textDim)
  set('--muted-foreground', merged.textDim)
  set('--border', merged.borderColor)
  set('--sidebar-border', merged.borderColor)
  set('--sidebar', merged.bgPanel)
  set('--sidebar-foreground', merged.textColor)

  const bodyStack = FONT_BODY_STACKS[merged.fontBody] || FONT_BODY_STACKS.Rajdhani
  const monoStack = FONT_MONO_STACKS[merged.fontMono] || FONT_MONO_STACKS['Fira Code']
  set('--font-body', bodyStack)
  set('--font-mono', monoStack)

  const baseFs = merged.fontSizeBase ?? merged.baseFontSize
  if (baseFs != null && baseFs !== '') {
    const b = clampFs(typeof baseFs === 'number' ? baseFs : Number(baseFs), 10, 24) ?? 15
    set('--font-size-base', `${b}px`)
    root.style.setProperty('font-size', `${b}px`)
  }

  set('--fs-nav', fsToPx(merged.fsNav, defaults.fsNav))
  set('--fs-chat', fsToPx(merged.fsChat, defaults.fsChat))
  set('--fs-input', fsToPx(merged.fsInput, defaults.fsInput))
  set('--fs-heading', fsToPx(merged.fsHeading, defaults.fsHeading))
  set('--fs-code', fsToPx(merged.fsCode, defaults.fsCode))

  const sw = merged.sidebarWidth
  if (typeof sw === 'number' && Number.isFinite(sw)) {
    const p = px(sw)
    set('--sidebar-width', p)
    set('--sources-panel-width', p)
  }
  const cmw = merged.chatMaxWidth
  if (typeof cmw === 'number' && Number.isFinite(cmw)) {
    const p = px(cmw)
    set('--chat-max-w', p)
    set('--chat-max-width', p)
  }

  if (typeof merged.title === 'string' && merged.title.trim()) {
    document.title = merged.title.trim()
  }
  const fav = merged.faviconUrl
  if (typeof fav === 'string' && fav.trim()) {
    let link = document.querySelector("link[rel~='icon']")
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      document.head.appendChild(link)
    }
    link.href = fav.trim()
  }

  useAppStore.getState().setBranding(merged)
  applyWorkspaceLayoutToDom()
}

export async function patchBrandingApi(patch) {
  return apiFetch('/api/branding/', { method: 'PATCH', json: patch })
}

export async function uploadBrandingAsset(slot, file) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/branding/upload/${slot}`, { method: 'POST', body: fd })
}

export async function deleteBrandingAsset(slot) {
  return apiFetch(`/api/branding/asset/${slot}`, { method: 'DELETE' })
}

/** Map `GET /api/settings/layout` onto branding fields used by `applyBrandingCss`. */
export function layoutApiToBrandingPatch(layout) {
  if (!layout || typeof layout !== 'object') return {}
  const { fontSize, ...rest } = layout
  const p = { ...rest }
  if (fontSize != null && fontSize !== '') {
    const n = typeof fontSize === 'number' ? fontSize : Number(fontSize)
    if (Number.isFinite(n)) {
      const b = Math.round(n)
      p.fontSizeBase = b
      p.baseFontSize = b
    }
  }
  return p
}

/** Global `ui_layout` settings carry a default palette; do not let them override per-workspace branding colors. */
const UI_LAYOUT_THEME_KEYS = new Set([
  'accentColor',
  'accentCyan',
  'accentPurple',
  'bgColor',
  'bgPanel',
  'bgCard',
  'textColor',
  'textDim',
  'borderColor',
])

/** Strip palette fields from layout payload before merging into workspace branding. */
export function layoutApiToBrandingPatchSansTheme(layoutApi) {
  const p = layoutApiToBrandingPatch(layoutApi)
  const out = { ...p }
  for (const k of UI_LAYOUT_THEME_KEYS) delete out[k]
  return out
}

export function mergeBrandingWithGlobalLayout(brandingRow, layoutApi, options = {}) {
  const patch =
    options.stripTheme === true ? layoutApiToBrandingPatchSansTheme(layoutApi) : layoutApiToBrandingPatch(layoutApi)
  return { ...(brandingRow && typeof brandingRow === 'object' ? brandingRow : {}), ...patch }
}

/** Fetch workspace branding and apply CSS + store. */
export async function fetchBranding() {
  const defaults = DEFAULT_BRANDING
  let row = defaults
  try {
    row = await apiFetch('/api/branding/')
  } catch {
    row = defaults
  }
  let layout = {}
  try {
    layout = await apiFetch('/api/settings/layout')
  } catch {
    layout = {}
  }
  useLayoutStore.getState().hydrateFromServer(layout && typeof layout === 'object' ? layout : {})
  // Strip palette from global layout so it doesn't stomp the per-workspace branding colors.
  const merged = mergeBrandingWithGlobalLayout(row, layout, { stripTheme: true })
  const finalized = patchBranding(null, merged)
  applyBrandingCss(finalized)
  return useAppStore.getState().branding
}
