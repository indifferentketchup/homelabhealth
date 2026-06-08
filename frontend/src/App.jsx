import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { AppRoutes } from '@/components/AppRoutes.jsx'
import { useAppStore } from '@/store/index.js'
import { Toaster } from '@/components/ui/sonner.jsx'

function LayoutBootstrap() {
  useEffect(() => {
    // Layout is loaded + applied to the DOM once, by WorkspaceApp.jsx
    // (loadLayout().then(applyWorkspaceLayoutToDom)). Calling it here too
    // double-fetched GET /api/settings/layout on every boot.
    void useAppStore.getState().bootstrapAuth()
  }, [])

  // Track on-screen-keyboard inset on iOS Safari (and any other browser that
  // exposes visualViewport). 100dvh stays static when the keyboard appears,
  // so we publish the keyboard height as --bc-keyboard-pad and consumers
  // (chat input padding, terminal pane, etc.) subtract it where needed.
  // Lives at the App root so it works app-wide.
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
        <LayoutBootstrap />
        <AppRoutes />
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
