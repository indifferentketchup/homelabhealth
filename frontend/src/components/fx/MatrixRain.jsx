import { useEffect, useRef, useState } from 'react'

const CHARSET = (() => {
  let s = ''
  for (let c = 0x41; c <= 0x5a; c++) s += String.fromCharCode(c)
  for (let c = 0x30; c <= 0x39; c++) s += String.fromCharCode(c)
  for (let c = 0xff66; c <= 0xff9d; c++) s += String.fromCharCode(c)
  return s
})()

const COL_WIDTH = 14
const TARGET_FPS = 24
const FRAME_BUDGET = 1000 / TARGET_FPS
const HEAD_COLOR = '#fbbf24'
const SECONDARY_COLOR = '#f97316'
const DEEP_COLOR = '#7a3d14'
const CLEAR_BG = '#0a0604'

function randChar() {
  return CHARSET.charAt((Math.random() * CHARSET.length) | 0)
}

export default function MatrixRain({ density = 0.35, speed = 0.7, enabled = true }) {
  const canvasRef = useRef(null)
  const [reducedMotion, setReducedMotion] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined
    const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = (e) => setReducedMotion(e.matches)
    if (typeof mql.addEventListener === 'function') mql.addEventListener('change', onChange)
    else if (typeof mql.addListener === 'function') mql.addListener(onChange)
    return () => {
      if (typeof mql.removeEventListener === 'function') mql.removeEventListener('change', onChange)
      else if (typeof mql.removeListener === 'function') mql.removeListener(onChange)
    }
  }, [])

  useEffect(() => {
    if (!enabled || reducedMotion) return undefined
    const canvas = canvasRef.current
    if (!canvas) return undefined
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return undefined

    let width = 0
    let height = 0
    let columns = 0
    let cols = []
    let rafId = null
    let lastTime = performance.now()
    let resizeTimer = null

    const setupCanvas = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = window.innerWidth
      height = window.innerHeight
      canvas.style.width = `${width}px`
      canvas.style.height = `${height}px`
      canvas.width = Math.floor(width * dpr)
      canvas.height = Math.floor(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.font = `${COL_WIDTH}px monospace`
      ctx.textBaseline = 'top'

      columns = Math.max(1, Math.floor((width / COL_WIDTH) * density))
      cols = new Array(columns)
      const rowsApprox = Math.ceil(height / COL_WIDTH) + 2
      for (let i = 0; i < columns; i++) {
        cols[i] = {
          y: -Math.floor(Math.random() * rowsApprox),
          step: 0.5 + Math.random() * 0.8,
        }
      }
      ctx.fillStyle = CLEAR_BG
      ctx.fillRect(0, 0, width, height)
    }

    const draw = () => {
      ctx.fillStyle = 'rgba(10, 6, 4, 0.08)'
      ctx.fillRect(0, 0, width, height)

      const effSpeed = Math.max(0.1, speed)
      const colPitch = columns > 0 ? width / columns : COL_WIDTH
      for (let i = 0; i < columns; i++) {
        const c = cols[i]
        const x = Math.floor(i * colPitch)
        const yPx = Math.floor(c.y) * COL_WIDTH

        if (c.y >= 0) {
          ctx.fillStyle = HEAD_COLOR
          ctx.fillText(randChar(), x, yPx)
          if (c.y >= 1) {
            ctx.fillStyle = SECONDARY_COLOR
            ctx.fillText(randChar(), x, yPx - COL_WIDTH)
          }
          if (c.y >= 2) {
            ctx.fillStyle = DEEP_COLOR
            ctx.fillText(randChar(), x, yPx - COL_WIDTH * 2)
          }
        }

        c.y += c.step * effSpeed

        const passedBottom = c.y * COL_WIDTH > height
        if (passedBottom && (Math.random() < 0.025 || c.y * COL_WIDTH > height + COL_WIDTH * 20)) {
          c.y = -1 - Math.floor(Math.random() * 8)
          c.step = 0.5 + Math.random() * 0.8
        }
      }
    }

    const loop = (now) => {
      rafId = window.requestAnimationFrame(loop)
      if (document.hidden) return
      const elapsed = now - lastTime
      if (elapsed < FRAME_BUDGET) return
      lastTime = now - (elapsed % FRAME_BUDGET)
      draw()
    }

    const start = () => {
      if (rafId != null) return
      lastTime = performance.now()
      rafId = window.requestAnimationFrame(loop)
    }
    const stop = () => {
      if (rafId != null) {
        window.cancelAnimationFrame(rafId)
        rafId = null
      }
    }
    const onVisibility = () => {
      if (document.hidden) stop()
      else start()
    }
    const onResize = () => {
      if (resizeTimer) window.clearTimeout(resizeTimer)
      resizeTimer = window.setTimeout(() => {
        setupCanvas()
      }, 150)
    }

    setupCanvas()
    if (!document.hidden) start()
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('resize', onResize)

    return () => {
      stop()
      if (resizeTimer) window.clearTimeout(resizeTimer)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', onResize)
    }
  }, [enabled, reducedMotion, density, speed])

  if (!enabled || reducedMotion) return null

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        width: '100vw',
        height: '100vh',
        zIndex: 50,
        pointerEvents: 'none',
        mixBlendMode: 'screen',
        opacity: 0.6,
      }}
    />
  )
}
