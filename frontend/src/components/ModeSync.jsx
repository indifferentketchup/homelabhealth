import { useLayoutEffect } from 'react'
import { useLocation } from 'react-router-dom'

import { applyMode, detectMode } from '@/mode.js'
import { useAppStore } from '@/store/index.js'

/** Keeps Zustand `mode` and `<html data-mode>` in sync with the current URL (path, query, host). */
export function ModeSync({ children }) {
  const { pathname, search } = useLocation()
  const setMode = useAppStore((s) => s.setMode)

  useLayoutEffect(() => {
    const mode = detectMode(window.location.hostname, search, pathname)
    setMode(mode)
    applyMode(mode)
  }, [pathname, search, setMode])

  return children
}
