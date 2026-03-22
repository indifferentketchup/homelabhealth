/**
 * BooOps (Phase 1) vs placeholder for other modes. Mode from `mode.js` / subdomain / VITE_APP_MODE.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

import BooOpsApp from '@/pages/booops/BooOpsApp.jsx'

import { APP_MODE } from './mode.js'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  if (APP_MODE === 'booops') {
    return (
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <BooOpsApp />
        </BrowserRouter>
      </QueryClientProvider>
    )
  }

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-2 bg-background px-6 text-center text-muted-foreground">
      <p className="text-sm font-medium text-foreground">boolab</p>
      <p className="max-w-md text-sm">
        {APP_MODE === '808notes'
          ? '808notes is not built in Phase 1. Use the BooOps subdomain or set VITE_APP_MODE=booops for local dev.'
          : 'Landing / boolab mode shell. Open the BooOps host or set VITE_APP_MODE=booops in .env for local chat.'}
      </p>
    </div>
  )
}
