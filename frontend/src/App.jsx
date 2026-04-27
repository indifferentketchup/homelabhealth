import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ModeSync } from '@/components/ModeSync.jsx'
import { ModeRouter } from '@/components/ModeRouter.jsx'
import { RootRedirect } from '@/components/RootRedirect.jsx'
import { USE_LEGACY_PATH_PREFIX } from '@/routes/paths.js'
import { useLayoutStore } from '@/store/layoutStore.js'
import { useAppStore } from '@/store/index.js'

function LayoutBootstrap() {
  useEffect(() => {
    void useLayoutStore.getState().loadLayout()
    void useAppStore.getState().bootstrapAuth()
  }, [])

  // Track on-screen-keyboard inset on iOS Safari (and any other browser that
  // exposes visualViewport). 100dvh stays static when the keyboard appears,
  // so we publish the keyboard height as --bc-keyboard-pad and consumers
  // (chat input padding, terminal pane, etc.) subtract it where needed.
  // Lives at the App root so it works in every mode (booops, 808notes,
  // boocode, boolab) — earlier this was scoped to BooCodeApp only.
  useEffect(() => {
    if (typeof window === 'undefined' || !window.visualViewport) return
    const apply = () => {
      // The space below the visible viewport = innerHeight − visualViewport.height − offsetTop.
      // Including offsetTop subtracts URL-bar height (when the URL bar is at
      // top and offsets the visible area down) so the published value is the
      // KEYBOARD height alone, not "URL-bar + keyboard". Without this
      // correction, position:fixed elements anchored at `bottom: var(--bc-keyboard-pad)`
      // land URL-bar pixels above the keyboard top, leaving a visible gap
      // (or pushing the input up to the top of the screen on browsers with
      // a tall top URL bar like Vivaldi).
      const inset = Math.max(
        0,
        window.innerHeight
          - window.visualViewport.height
          - window.visualViewport.offsetTop,
      )
      document.documentElement.style.setProperty('--bc-keyboard-pad', `${inset}px`)
    }
    apply()
    window.visualViewport.addEventListener('resize', apply)
    window.visualViewport.addEventListener('scroll', apply)
    return () => {
      window.visualViewport.removeEventListener('resize', apply)
      window.visualViewport.removeEventListener('scroll', apply)
    }
  }, [])

  return null
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ModeSync>
          <LayoutBootstrap />
          <Routes>
            {USE_LEGACY_PATH_PREFIX ? (
              <>
                <Route path="/" element={<RootRedirect />} />
                <Route path="/*" element={<ModeRouter />} />
              </>
            ) : (
              <Route path="/*" element={<ModeRouter />} />
            )}
          </Routes>
        </ModeSync>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
