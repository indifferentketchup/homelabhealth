const STORAGE_KEY = 'hlh:theme'

function applyThemeClass(theme) {
  const root = document.documentElement
  if (theme === 'dark') {
    root.classList.add('dark')
  } else if (theme === 'light') {
    root.classList.remove('dark')
  } else {
    // 'system'
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches
    if (prefersDark) root.classList.add('dark')
    else root.classList.remove('dark')
  }
}

// Module-scoped listener tracking so initTheme can be called multiple times
// idempotently (e.g., from main.jsx + HMR).
let _mqListener = null
let _mq = null

function attachSystemListener(getCurrentTheme) {
  if (_mqListener) return
  _mq = window.matchMedia('(prefers-color-scheme: dark)')
  _mqListener = () => {
    if (getCurrentTheme() === 'system') applyThemeClass('system')
  }
  _mq.addEventListener('change', _mqListener)
}

export const createThemeSlice = (set, get) => ({
  theme: (typeof localStorage !== 'undefined' && localStorage.getItem(STORAGE_KEY)) || 'system',
  setTheme: (next) => {
    if (!['light', 'dark', 'system'].includes(next)) return
    localStorage.setItem(STORAGE_KEY, next)
    applyThemeClass(next)
    set({ theme: next })
  },
  initTheme: () => {
    const current = get().theme
    applyThemeClass(current)
    attachSystemListener(() => get().theme)
  },
})
