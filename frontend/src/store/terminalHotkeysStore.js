import { create } from 'zustand'

// Catalog of preset hotkeys. Each entry either ships `bytes` (sent over the
// terminal websocket as-is) or `sticky` (a UI-only modifier that arms the
// next on-screen keystroke). Adding a new key here makes it available in the
// settings catalog without any other wiring.
export const HOTKEY_CATALOG = [
  { id: 'esc', label: 'Esc', bytes: '\x1b' },
  { id: 'tab', label: 'Tab', bytes: '\t' },
  { id: 'shift-tab', label: '⇧Tab', bytes: '\x1b[Z' },
  { id: 'enter', label: 'Enter', bytes: '\r' },
  { id: 'arrow-up', label: '↑', bytes: '\x1b[A' },
  { id: 'arrow-down', label: '↓', bytes: '\x1b[B' },
  { id: 'arrow-left', label: '←', bytes: '\x1b[D' },
  { id: 'arrow-right', label: '→', bytes: '\x1b[C' },
  { id: 'ctrl', label: 'Ctrl', sticky: 'ctrl' },
  { id: 'ctrl-c', label: 'Ctrl+C', bytes: '\x03' },
  { id: 'ctrl-d', label: 'Ctrl+D', bytes: '\x04' },
  { id: 'ctrl-z', label: 'Ctrl+Z', bytes: '\x1a' },
  { id: 'ctrl-l', label: 'Ctrl+L', bytes: '\x0c' },
  { id: 'ctrl-r', label: 'Ctrl+R', bytes: '\x12' },
  { id: 'ctrl-a', label: 'Ctrl+A', bytes: '\x01' },
  { id: 'ctrl-e', label: 'Ctrl+E', bytes: '\x05' },
  { id: 'ctrl-u', label: 'Ctrl+U', bytes: '\x15' },
  { id: 'ctrl-w', label: 'Ctrl+W', bytes: '\x17' },
  { id: 'ctrl-k', label: 'Ctrl+K', bytes: '\x0b' },
  { id: 'ctrl-p', label: 'Ctrl+P', bytes: '\x10' },
  { id: 'home', label: 'Home', bytes: '\x1b[H' },
  { id: 'end', label: 'End', bytes: '\x1b[F' },
  { id: 'pgup', label: 'PgUp', bytes: '\x1b[5~' },
  { id: 'pgdn', label: 'PgDn', bytes: '\x1b[6~' },
]

const CATALOG_BY_ID = Object.fromEntries(HOTKEY_CATALOG.map((k) => [k.id, k]))

export function getHotkey(id) {
  return CATALOG_BY_ID[id] || null
}

export const DEFAULT_BAR = [
  'shift-tab',
  'tab',
  'ctrl',
  'ctrl-c',
  'arrow-up',
  'arrow-down',
  'arrow-left',
  'arrow-right',
]

const STORAGE_KEY = 'boocode-terminal-hotkeys-v1'

function readStorage() {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null
  }
}

function writeStorage(state) {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ bar: state.bar, visible: state.visible }),
    )
  } catch {
    /* quota / disabled — non-fatal */
  }
}

function sanitizeBar(input) {
  if (!Array.isArray(input)) return DEFAULT_BAR.slice()
  const seen = new Set()
  const out = []
  for (const id of input) {
    if (typeof id !== 'string') continue
    if (!CATALOG_BY_ID[id]) continue
    if (seen.has(id)) continue
    seen.add(id)
    out.push(id)
  }
  return out
}

const persisted = readStorage()
const initial = {
  bar: persisted ? sanitizeBar(persisted.bar) : DEFAULT_BAR.slice(),
  visible: persisted && typeof persisted.visible === 'boolean' ? persisted.visible : true,
}

export const useTerminalHotkeysStore = create((set, get) => ({
  ...initial,

  setBar(next) {
    const sanitized = sanitizeBar(next)
    set({ bar: sanitized })
    writeStorage({ ...get(), bar: sanitized })
  },

  addToBar(id) {
    const cur = get().bar
    if (cur.includes(id) || !CATALOG_BY_ID[id]) return
    const next = [...cur, id]
    set({ bar: next })
    writeStorage({ ...get(), bar: next })
  },

  removeFromBar(id) {
    const cur = get().bar
    if (!cur.includes(id)) return
    const next = cur.filter((x) => x !== id)
    set({ bar: next })
    writeStorage({ ...get(), bar: next })
  },

  moveBar(id, direction) {
    const cur = get().bar
    const i = cur.indexOf(id)
    if (i < 0) return
    const j = direction === 'up' ? i - 1 : i + 1
    if (j < 0 || j >= cur.length) return
    const next = cur.slice()
    next[i] = cur[j]
    next[j] = cur[i]
    set({ bar: next })
    writeStorage({ ...get(), bar: next })
  },

  setVisible(v) {
    const visible = !!v
    set({ visible })
    writeStorage({ ...get(), visible })
  },

  reset() {
    const next = { bar: DEFAULT_BAR.slice(), visible: true }
    set(next)
    writeStorage(next)
  },
}))
