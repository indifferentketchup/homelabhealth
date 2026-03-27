import { apiFetch } from '@/api/index.js'
import { apply808notesLayoutToDom } from '@/lib/notes808Layout.js'
import { applyMode } from '@/mode.js'
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

/** Default BooOps branding (aligned with API `/api/branding/booops` merge base). */
export const DEFAULT_BOOOPS_BRANDING = {
  accentColor: '#ff2d78',
  accentCyan: '#00e5ff',
  accentPurple: '#9b5de5',
  bgColor: '#080b14',
  bgPanel: '#0d1120',
  bgCard: '#0f1525',
  textColor: '#cde0ff',
  textDim: '#5a7a9e',
  borderColor: '#1e2d50',
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
  /** Lucide icon name for settings / branding UI (optional URL asset later). */
  appGlyphIcon: 'Bot',
}

/** Hub (`/boolab`) branding — aligned with `/api/branding/boolab`. */
export const DEFAULT_BOOLAB_BRANDING = {
  title: 'BooLab',
  tagline: '// pick your lab bench.',
  hubDisplayFont: 'JetBrains Mono',
  hubMonoFont: 'Share Tech Mono',
  accentColor: '#5dcf8f',
  bgColor: '#050807',
  bgPanel: '#0a100c',
  bgCard: '#0d1510',
  textColor: 'rgba(200, 230, 210, 0.92)',
  textDim: 'rgba(120, 160, 140, 0.65)',
  borderColor: 'rgba(93, 207, 143, 0.18)',
  bannerUrl: '',
  logoUrl: '',
  faviconUrl: '',
  appGlyphIcon: 'FlaskConical',
  booopsCard: {
    icon: 'Bot',
    iconUrl: '',
    iconSize: 44,
    accent: '#4ade80',
    title: 'BooOps',
    description: 'LLM chat — personas, DAWs, memory.',
  },
  notes808Card: {
    icon: 'Music2',
    iconUrl: '',
    iconSize: 44,
    accent: '#34d399',
    title: '808notes',
    description: 'Music notes, sources, and project context.',
  },
  /** `center` | `start` | `end` — hub landing app cards */
  hubCardsTextAlign: 'center',
  /** Multiplier for card title, body, and icon (~0.75–1.5). */
  hubCardsFontScale: 1,
  /** Hero title, tagline, “core”, footer, banner badge (~0.75–1.5). */
  hubLandingFontScale: 1,
  /** Hero logo tile + glyph, hub card icons (~0.75–1.35). */
  hubLandingIconScale: 1,
}

export const FONT_HUB_DISPLAY_OPTIONS = [
  'JetBrains Mono',
  'Share Tech Mono',
  'Oxanium',
  'Exo 2',
  'Space Grotesk',
  'DM Sans',
  'Rajdhani',
  'Cinzel',
  'Orbitron',
  'IBM Plex Sans',
]

/** @param {string} id */
function ensureStylesheetLink(id, href) {
  let link = document.getElementById(id)
  if (!link) {
    link = document.createElement('link')
    link.id = id
    link.rel = 'stylesheet'
    document.head.appendChild(link)
  }
  if (href && link.getAttribute('href') !== href) {
    link.setAttribute('href', href)
  }
}

/**
 * Load Google Fonts for the hub title / tagline. Idempotent; updates href when families change.
 * @param {string} [displayFont]
 * @param {string} [monoFont]
 */
export function injectHubGoogleFonts(displayFont, monoFont) {
  const d = typeof displayFont === 'string' ? displayFont.trim() : ''
  const m = typeof monoFont === 'string' ? monoFont.trim() : ''
  const parts = []
  if (d) parts.push(`family=${encodeURIComponent(d).replace(/%20/g, '+')}:wght@400;600;700;800`)
  if (m && m !== d) parts.push(`family=${encodeURIComponent(m).replace(/%20/g, '+')}:wght@400;500;600`)
  if (!parts.length) return
  const href = `https://fonts.googleapis.com/css2?${parts.join('&')}&display=swap`
  ensureStylesheetLink('boolab-hub-google-fonts', href)
}

/** Merge boolab branding with defaults (nested cards). */
export function patchBoolabBranding(base, partial) {
  const merged = {
    ...DEFAULT_BOOLAB_BRANDING,
    ...(base && typeof base === 'object' ? base : {}),
    ...(partial && typeof partial === 'object' ? partial : {}),
  }
  merged.booopsCard = {
    ...DEFAULT_BOOLAB_BRANDING.booopsCard,
    ...(base?.booopsCard && typeof base.booopsCard === 'object' ? base.booopsCard : {}),
    ...(partial?.booopsCard && typeof partial.booopsCard === 'object' ? partial.booopsCard : {}),
  }
  merged.notes808Card = {
    ...DEFAULT_BOOLAB_BRANDING.notes808Card,
    ...(base?.notes808Card && typeof base.notes808Card === 'object' ? base.notes808Card : {}),
    ...(partial?.notes808Card && typeof partial.notes808Card === 'object' ? partial.notes808Card : {}),
  }
  return merged
}

export async function fetchBoolabBranding() {
  try {
    const row = await apiFetch('/api/branding/boolab')
    return patchBoolabBranding(null, row)
  } catch {
    return patchBoolabBranding(null, DEFAULT_BOOLAB_BRANDING)
  }
}

export async function updateBoolabBranding(patch) {
  return apiFetch('/api/branding/boolab', { method: 'PATCH', json: patch })
}

export async function uploadBoolabAsset(slot, file) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/branding/boolab/upload/${slot}`, { method: 'POST', body: fd })
}

export async function deleteBoolabAsset(slot) {
  return apiFetch(`/api/branding/boolab/asset/${slot}`, { method: 'DELETE' })
}

/** Default 808notes branding (aligned with API `/api/branding/808notes`). */
export const DEFAULT_808NOTES_BRANDING = {
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
  title: '808notes',
  /** Landing hero line under the title (editable in Settings → Branding). */
  subtitle: '// pick your desk. open a daw workspace.',
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
  return mergeBrandingDefaults(DEFAULT_BOOOPS_BRANDING, base, partial)
}

/** Like `patchBranding` but for 808notes defaults (persona chat + branding settings). */
export function patch808notesBranding(base, partial) {
  const merged = {
    ...DEFAULT_808NOTES_BRANDING,
    ...(base && typeof base === 'object' ? base : {}),
    ...(partial && typeof partial === 'object' ? partial : {}),
  }
  // DB/API may store null; spread would otherwise wipe defaults and empty the landing tagline.
  if (merged.title == null) merged.title = DEFAULT_808NOTES_BRANDING.title
  if (merged.subtitle == null) merged.subtitle = DEFAULT_808NOTES_BRANDING.subtitle
  return finalizeBranding(merged, DEFAULT_808NOTES_BRANDING)
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
 * @param {'booops' | '808notes' | null} brandingMode When set, drives default palette and syncs `<html data-mode>` so a cold load or cache clear cannot leave `boolab` and skip 808 styling. When null, uses current `document.documentElement.dataset.mode`.
 */
export function applyBrandingCss(config, brandingMode = null) {
  const root = document.documentElement
  if (brandingMode === 'booops' || brandingMode === '808notes') {
    applyMode(brandingMode)
  }
  const mode =
    brandingMode === 'booops' || brandingMode === '808notes' ? brandingMode : root.dataset.mode
  if (mode !== 'booops' && mode !== '808notes') return

  const defaults = mode === '808notes' ? DEFAULT_808NOTES_BRANDING : DEFAULT_BOOOPS_BRANDING
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
    if (mode === '808notes') set('--sources-panel-width', p)
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
  if (mode === '808notes') {
    apply808notesLayoutToDom()
  }
}

export async function updateBranding(patch) {
  return apiFetch('/api/branding/booops', { method: 'PUT', json: patch })
}

export async function uploadBrandingAsset(slot, file) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/branding/booops/upload/${slot}`, { method: 'POST', body: fd })
}

export async function deleteBrandingAsset(slot) {
  return apiFetch(`/api/branding/booops/asset/${slot}`, { method: 'DELETE' })
}

export async function patchBranding808notes(patch) {
  return apiFetch('/api/branding/808notes', { method: 'PATCH', json: patch })
}

export async function uploadBrandingAsset808notes(slot, file) {
  const fd = new FormData()
  fd.append('file', file)
  return apiFetch(`/api/branding/808notes/upload/${slot}`, { method: 'POST', body: fd })
}

export async function deleteBrandingAsset808notes(slot) {
  return apiFetch(`/api/branding/808notes/asset/${slot}`, { method: 'DELETE' })
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

/** `ui_layout` global settings default to BooOps palette; do not let them override 808notes branding colors. */
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

/** Strip palette fields from layout payload before merging into 808notes branding (global layout defaults are BooOps). */
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

/** Fetch branding for a mode and apply CSS + store (see `applyBrandingCss`). */
export async function fetchBranding(mode) {
  const m = mode === '808notes' ? '808notes' : mode === 'booops' ? 'booops' : 'booops'
  const defaults = m === '808notes' ? DEFAULT_808NOTES_BRANDING : DEFAULT_BOOOPS_BRANDING
  let row = defaults
  try {
    row = await apiFetch(`/api/branding/${m}`)
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
  const merged = mergeBrandingWithGlobalLayout(row, layout, { stripTheme: m === '808notes' })
  const finalized = m === '808notes' ? patch808notesBranding(null, merged) : patchBranding(null, merged)
  applyBrandingCss(finalized, m)
  return useAppStore.getState().branding
}
