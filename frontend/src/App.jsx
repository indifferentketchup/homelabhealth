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
