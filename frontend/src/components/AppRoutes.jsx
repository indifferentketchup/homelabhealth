import { useEffect, useState } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import {
  WorkspaceLanding,
  WorkspaceLayout,
  WorkspaceChat,
  WorkspaceSourcesPage,
  WorkspaceAuxShell,
} from '@/pages/workspace/WorkspaceView.jsx'
import WorkspaceApp, { SettingsRoute } from '@/pages/workspace/WorkspaceApp.jsx'
import WorkspacesPage from '@/pages/workspace/WorkspacesPage.jsx'
import WorkspaceDetailPage from '@/pages/workspace/WorkspaceDetailPage.jsx'
import AISettings from '@/pages/workspace/AISettings.jsx'
import ProfilePage from '@/pages/workspace/ProfilePage.jsx'
import RequireSetup from '@/components/RequireSetup.jsx'
import LoginPage from '@/pages/LoginPage.jsx'
import SetupPage from '@/pages/SetupPage.jsx'

/**
 * Auth guard: checks /api/auth/needs-setup and /api/auth/me on mount.
 * - needs_setup → redirect to /setup
 * - not authenticated → redirect to /login
 * - authenticated → render children
 */
function AuthGuard({ children }) {
  const [state, setState] = useState('loading') // 'loading' | 'setup' | 'login' | 'authenticated'

  useEffect(() => {
    async function check() {
      try {
        // Check if setup is needed (no session required for this endpoint)
        const setupRes = await fetch('/api/auth/needs-setup')
        const setupData = await setupRes.json()
        if (setupData.needs_setup) {
          setState('setup')
          return
        }
        // Check if authenticated
        const meRes = await fetch('/api/auth/me', { credentials: 'same-origin' })
        if (meRes.ok) {
          setState('authenticated')
        } else {
          setState('login')
        }
      } catch {
        setState('login')
      }
    }
    check()
  }, [])

  if (state === 'loading') return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="space-y-1 text-center">
        <p className="text-xl font-semibold text-foreground">HomeLab Health</p>
        <p className="text-sm text-muted-foreground">Loading…</p>
      </div>
    </div>
  )
  if (state === 'setup') return <Navigate to="/setup" replace />
  if (state === 'login') return <Navigate to="/login" replace />
  return children
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/setup" element={<SetupPage />} />
      {/* All app routes wrapped in AuthGuard, which gates on a valid session */}
      <Route path="/*" element={
        <AuthGuard>
          <Routes>
            {/* First-boot gate: when system_profile.setup_complete is false, the
                operator is redirected to /settings?tab=system until they confirm
                a tier. Phase 0; see frontend/src/components/RequireSetup.jsx. */}
            <Route element={<RequireSetup />}>
              <Route path="/" element={<WorkspaceApp />}>
                <Route index element={<WorkspaceLanding />} />
                <Route path="workspaces" element={<WorkspacesPage />} />
                <Route path="workspaces/:id" element={<WorkspaceDetailPage />} />
                <Route path="workspace/:workspaceId" element={<WorkspaceLayout />}>
                  <Route index element={<WorkspaceChat />} />
                  <Route path="sources" element={<WorkspaceSourcesPage />} />
                </Route>
                <Route element={<WorkspaceAuxShell />}>
                  <Route path="ai" element={<AISettings />} />
                  <Route path="settings" element={<SettingsRoute />} />
                  <Route path="profile" element={<ProfilePage />} />
                </Route>
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Route>
          </Routes>
        </AuthGuard>
      } />
    </Routes>
  )
}
