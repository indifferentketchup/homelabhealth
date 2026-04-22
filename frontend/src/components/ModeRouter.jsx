import { useMemo } from 'react'
import { useNavigate, Routes, Route, Navigate } from 'react-router-dom'
import { detectMode } from '@/mode.js'
import {
  USE_LEGACY_PATH_PREFIX,
  PATH_BOOLAB,
  PATH_BOOLAB_HOME,
  PATH_808NOTES,
  PATH_808NOTES_HOME,
} from '@/routes/paths.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import BooOpsApp from '@/pages/booops/BooOpsApp.jsx'
import Notes808App, { Notes808SettingsRoute } from '@/pages/notes808/Notes808App.jsx'
import {
  Notes808Landing,
  Notes808DawLayout,
  Notes808DawChat,
  Notes808DawSourcesPage,
  Notes808AuxShell,
} from '@/pages/notes808/Notes808Workspace.jsx'
import BooCodeApp, { BooCodeSettingsRoute } from '@/pages/boocode/BooCodeApp.jsx'
import BooCodeLanding from '@/pages/boocode/BooCodeLanding.jsx'
import BooCodeDawWorkspace from '@/pages/boocode/BooCodeDawWorkspace.jsx'
import AISettings from '@/pages/booops/AISettings.jsx'
import AllChats from '@/pages/booops/AllChats.jsx'
import { BooOpsDawChat } from '@/pages/booops/BooOpsDawChat.jsx'
import DawDetailPage from '@/pages/booops/DawDetailPage.jsx'
import DawsPage from '@/pages/booops/DawsPage.jsx'
import ProfilePage from '@/pages/booops/ProfilePage.jsx'
import SettingsPage from '@/pages/booops/SettingsPage.jsx'
import BoolabLanding from '@/pages/BoolabLanding.jsx'
import BoolabBranding from '@/pages/BoolabBranding.jsx'
import { SkillsLibraryPage } from '@/pages/SkillsLibraryPage.jsx'

function BooOpsSettingsRoute() {
  const navigate = useNavigate()
  return <SettingsPage mode="booops" onClose={() => navigate('/')} />
}

export function ModeRouter() {
  const mode = useMemo(() => detectMode(), [])
  const notes808Root = USE_LEGACY_PATH_PREFIX ? PATH_808NOTES : '/'
  
  if (mode === 'booops') {
    return (
      <Routes>
        <Route path="/" element={<BooOpsApp />}>
          <Route index element={<ChatView />} />
          <Route path="daw/:dawId" element={<BooOpsDawChat />} />
          <Route path="chats" element={<AllChats />} />
          <Route path="daws" element={<DawsPage />} />
          <Route path="daws/:id" element={<DawDetailPage />} />
          <Route path="ai" element={<AISettings />} />
          <Route path="settings" element={<BooOpsSettingsRoute />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="skills" element={<SkillsLibraryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }
  
  if (mode === '808notes') {
    return (
      <Routes>
        <Route path={notes808Root} element={<Notes808App />}>
          <Route index element={<Notes808Landing />} />
          <Route path="daws" element={<DawsPage />} />
          <Route path="daws/:id" element={<DawDetailPage />} />
          <Route path="daw/:dawId" element={<Notes808DawLayout />}>
            <Route index element={<Notes808DawChat />} />
            <Route path="sources" element={<Notes808DawSourcesPage />} />
          </Route>
          <Route element={<Notes808AuxShell />}>
            <Route path="ai" element={<AISettings />} />
            <Route path="settings" element={<Notes808SettingsRoute />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="skills" element={<SkillsLibraryPage />} />
          </Route>
          <Route path="*" element={<Navigate to={PATH_808NOTES_HOME} replace />} />
        </Route>
      </Routes>
    )
  }

  if (mode === 'boocode') {
    return (
      <Routes>
        <Route path="/" element={<BooCodeApp />}>
          <Route index element={<BooCodeLanding />} />
          <Route path="daw/:dawId" element={<BooCodeDawWorkspace />} />
          <Route path="daws" element={<DawsPage />} />
          <Route path="daws/:id" element={<DawDetailPage />} />
          <Route path="ai" element={<AISettings />} />
          <Route path="settings" element={<BooCodeSettingsRoute />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="skills" element={<SkillsLibraryPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    )
  }

  if (USE_LEGACY_PATH_PREFIX) {
    return (
      <Routes>
        <Route path={PATH_BOOLAB} element={<BoolabLanding />} />
        <Route path={`${PATH_BOOLAB}/ai`} element={<AISettings />} />
        <Route path={`${PATH_BOOLAB}/branding`} element={<BoolabBranding />} />
        <Route path="*" element={<Navigate to={PATH_BOOLAB_HOME} replace />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/" element={<BoolabLanding />} />
      <Route path="ai" element={<AISettings />} />
      <Route path="branding" element={<BoolabBranding />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
