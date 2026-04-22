import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
  useSyncExternalStore,
} from 'react'

import { useAppStore } from '@/store/index.js'

const MATRIX_KEY = 'boocode:fx:matrix'
const CRT_KEY = 'boocode:fx:crt'

const DEFAULT_DENSITY = 0.35
const DEFAULT_SPEED = 0.7
const DEFAULT_MATRIX_OPACITY = 0.6
const DEFAULT_CRT_OPACITY = 0.7

let cachedIsMobile = null
function isMobileViewport() {
  if (cachedIsMobile !== null) return cachedIsMobile
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    cachedIsMobile = false
  } else {
    cachedIsMobile = window.matchMedia('(max-width: 768px)').matches
  }
  return cachedIsMobile
}

function readFlag(key) {
  if (typeof window === 'undefined') return !isMobileViewport()
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === null) return !isMobileViewport()
    return raw === '1' || raw === 'true'
  } catch {
    return !isMobileViewport()
  }
}

const fxListeners = new Set()
function notifyFx() {
  fxListeners.forEach((fn) => fn())
}

function subscribeFx(cb) {
  fxListeners.add(cb)
  return () => {
    fxListeners.delete(cb)
  }
}

function writeFlag(key, value) {
  try {
    window.localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* quota / private mode — ignore */
  }
  notifyFx()
}

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (e) => {
    if (e.key === MATRIX_KEY || e.key === CRT_KEY) notifyFx()
  })
}

const getMatrixSnap = () => readFlag(MATRIX_KEY)
const getCrtSnap = () => readFlag(CRT_KEY)

export function useBoocodeFx() {
  const matrixEnabled = useSyncExternalStore(subscribeFx, getMatrixSnap, getMatrixSnap)
  const crtEnabled = useSyncExternalStore(subscribeFx, getCrtSnap, getCrtSnap)
  const branding = useAppStore((s) => s.branding)

  const setMatrixEnabled = useCallback((value) => {
    writeFlag(MATRIX_KEY, Boolean(value))
  }, [])
  const setCrtEnabled = useCallback((value) => {
    writeFlag(CRT_KEY, Boolean(value))
  }, [])

  const rawDensity = Number(branding?.matrixRainDensity)
  const rawSpeed = Number(branding?.matrixRainSpeed)
  const rawMatrixOpacity = Number(branding?.matrixRainOpacity)
  const rawCrtOpacity = Number(branding?.crtOverlayOpacity)
  const density = Number.isFinite(rawDensity) ? rawDensity : DEFAULT_DENSITY
  const speed = Number.isFinite(rawSpeed) ? rawSpeed : DEFAULT_SPEED
  const matrixOpacity = Number.isFinite(rawMatrixOpacity) ? rawMatrixOpacity : DEFAULT_MATRIX_OPACITY
  const crtOpacity = Number.isFinite(rawCrtOpacity) ? rawCrtOpacity : DEFAULT_CRT_OPACITY

  return {
    matrixEnabled, crtEnabled, setMatrixEnabled, setCrtEnabled,
    density, speed, matrixOpacity, crtOpacity,
  }
}

const FxSuppressStateContext = createContext({ suppressMatrix: false, suppressCrt: false })
const FxSuppressControlContext = createContext({
  registerMatrix: () => () => {},
  registerCrt: () => () => {},
})

export function FxSuppressProvider({ children }) {
  const [matrixIds, setMatrixIds] = useState(() => new Set())
  const [crtIds, setCrtIds] = useState(() => new Set())

  const controls = useMemo(
    () => ({
      registerMatrix: (id) => {
        setMatrixIds((prev) => {
          if (prev.has(id)) return prev
          const next = new Set(prev)
          next.add(id)
          return next
        })
        return () => {
          setMatrixIds((prev) => {
            if (!prev.has(id)) return prev
            const next = new Set(prev)
            next.delete(id)
            return next
          })
        }
      },
      registerCrt: (id) => {
        setCrtIds((prev) => {
          if (prev.has(id)) return prev
          const next = new Set(prev)
          next.add(id)
          return next
        })
        return () => {
          setCrtIds((prev) => {
            if (!prev.has(id)) return prev
            const next = new Set(prev)
            next.delete(id)
            return next
          })
        }
      },
    }),
    [],
  )

  const state = useMemo(
    () => ({ suppressMatrix: matrixIds.size > 0, suppressCrt: crtIds.size > 0 }),
    [matrixIds, crtIds],
  )

  return (
    <FxSuppressControlContext.Provider value={controls}>
      <FxSuppressStateContext.Provider value={state}>{children}</FxSuppressStateContext.Provider>
    </FxSuppressControlContext.Provider>
  )
}

export function useFxSuppress({ matrix = false, crt = false } = {}) {
  const { registerMatrix, registerCrt } = useContext(FxSuppressControlContext)
  const id = useId()
  useEffect(() => {
    const cleanups = []
    if (matrix) cleanups.push(registerMatrix(id))
    if (crt) cleanups.push(registerCrt(id))
    return () => cleanups.forEach((fn) => fn())
  }, [matrix, crt, id, registerMatrix, registerCrt])
}

export function useFxSuppressState() {
  return useContext(FxSuppressStateContext)
}
