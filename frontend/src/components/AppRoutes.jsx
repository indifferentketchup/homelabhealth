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

export function AppRoutes() {
  return (
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
  )
}
