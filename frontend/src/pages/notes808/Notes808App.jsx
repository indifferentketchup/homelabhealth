import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, matchPath, useLocation, useNavigate } from 'react-router-dom'
import { FileStack, Menu } from 'lucide-react'

import { fetchBranding } from '@/api/branding.js'
import { getOllamaSettings } from '@/api/ollama.js'
import { listPersonas } from '@/api/personas.js'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { DawQuerySync } from '@/components/DawQuerySync.jsx'
import { Sidebar } from '@/components/layout/Sidebar.jsx'
import { UserProfileMenu } from '@/components/layout/UserProfileMenu.jsx'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { apply808notesLayoutToDom, clear808notesLayoutLiveDraft } from '@/lib/notes808Layout.js'
import { PATH_808NOTES, PATH_808NOTES_HOME, notes808DawPath } from '@/routes/paths.js'
import SettingsPage from '@/pages/booops/SettingsPage.jsx'
import { useAppStore } from '@/store/index.js'

import { SourcesPanel } from './SourcesPanel.jsx'

import './Notes808App.css'

/** @deprecated Routed DAW listing lives on the landing page; kept for deep links. */
export { default as DawsPage } from '@/pages/booops/DawsPage.jsx'

export function Notes808SettingsRoute() {
  const navigate = useNavigate()
  const closeSettings = useCallback(() => {
    clear808notesLayoutLiveDraft()
    navigate(PATH_808NOTES_HOME, { replace: true })
  }, [navigate])

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background md:min-h-0"
      role="region"
      aria-labelledby="settings-title"
    >
      <SettingsPage mode="808notes" onClose={closeSettings} />
    </div>
  )
}

export default function Notes808App() {
  const location = useLocation()
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [mobileSourcesOpen, setMobileSourcesOpen] = useState(false)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const activeDawId = useAppStore((s) => s.activeDawId)
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setDefaultModel = useAppStore((s) => s.setDefaultModel)
  const hydrateUserProfile = useAppStore((s) => s.hydrateUserProfile)

  const { aiPath, settingsPath, profilePath } = useMemo(() => {
    const b = PATH_808NOTES.replace(/\/$/, '')
    return {
      aiPath: b ? `${b}/ai` : '/ai',
      settingsPath: b ? `${b}/settings` : '/settings',
      profilePath: b ? `${b}/profile` : '/profile',
    }
  }, [])

  const isLanding = Boolean(
    matchPath({ path: PATH_808NOTES_HOME, end: true }, location.pathname),
  )

  useEffect(() => {
    if (!isLanding) return
    setActiveDawId(null)
    setActiveChatId(null)
  }, [isLanding, setActiveDawId, setActiveChatId])

  const isAuxRoute = Boolean(
    matchPath({ path: aiPath, end: true }, location.pathname) ||
      matchPath({ path: settingsPath, end: true }, location.pathname) ||
      matchPath({ path: profilePath, end: true }, location.pathname),
  )
  const onDawSourcesPage = /\/sources\/?$/.test(location.pathname)
  const showDawSourcesShortcut =
    !isLanding && !isAuxRoute && Boolean(activeDawId) && !onDawSourcesPage

  const { data: ollamaSettingsBoot } = useQuery({
    queryKey: ['ollama', 'settings', '808notes'],
    queryFn: () => getOllamaSettings('808notes'),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (ollamaSettingsBoot?.default_model != null) setDefaultModel(ollamaSettingsBoot.default_model)
  }, [ollamaSettingsBoot?.default_model, setDefaultModel])

  const { data: personaPack } = useQuery({
    queryKey: ['personas'],
    queryFn: () => listPersonas(),
    staleTime: 60_000,
  })

  useEffect(() => {
    const items = personaPack?.items
    if (Array.isArray(items)) setPersonas(items)
  }, [personaPack, setPersonas])

  useEffect(() => {
    hydrateUserProfile()
  }, [hydrateUserProfile])

  useEffect(() => {
    const fn = () => apply808notesLayoutToDom()
    window.addEventListener('808notes-layout', fn)
    return () => window.removeEventListener('808notes-layout', fn)
  }, [])

  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const apply = () => {
      if (mq.matches) setMobileSourcesOpen(false)
    }
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])

  useEffect(() => {
    if (!mobileSourcesOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') setMobileSourcesOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [mobileSourcesOpen])

  const { isPending: brandingPending } = useQuery({
    queryKey: ['branding', '808notes'],
    queryFn: () => fetchBranding('808notes'),
    staleTime: 60_000,
    retry: false,
  })

  if (brandingPending) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center bg-background text-muted-foreground">
        Loading…
      </div>
    )
  }

  return (
    <TooltipProvider>
      <DawQuerySync />
      <div
        className="layout flex h-[100dvh] w-full overflow-clip bg-background text-foreground md:flex-row"
        data-mode="808notes"
      >
        <Sidebar
          appMode="808notes"
          routeBase={PATH_808NOTES}
          mobileOpen={mobileSidebar}
          onMobileOpenChange={(open) => {
            setMobileSidebar(open)
            if (open) setMobileSourcesOpen(false)
          }}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex min-w-0 items-center gap-2 border-b border-border bg-background px-2 py-2 md:hidden">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Open sidebar"
              onClick={() => setMobileSidebar(true)}
            >
              <Menu className="size-5" />
            </Button>
            {!isLanding ? <ModelSelectorBar className="min-w-0 flex-1" /> : <div className="min-w-0 flex-1" />}
            <UserProfileMenu
              profilePath={profilePath}
              homePath={PATH_808NOTES_HOME}
              placement="header"
              onAfterNavigate={() => setMobileSidebar(false)}
            />
            {isAuxRoute ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                aria-label="Open sources panel"
                onClick={() => {
                  setMobileSidebar(false)
                  setMobileSourcesOpen(true)
                }}
              >
                <FileStack className="size-5" />
              </Button>
            ) : showDawSourcesShortcut ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                asChild
                aria-label="Sources"
              >
                <Link
                  to={notes808DawPath(activeDawId, 'sources')}
                  onClick={() => setMobileSourcesOpen(false)}
                >
                  <FileStack className="size-5" />
                </Link>
              </Button>
            ) : null}
          </header>
          <UserProfileMenu profilePath={profilePath} homePath={PATH_808NOTES_HOME} placement="fixed" />
          <main className="main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <Outlet />
          </main>
        </div>

        {mobileSourcesOpen && (
          <>
            <button
              type="button"
              className="fixed inset-0 z-30 bg-background/70 md:hidden"
              aria-label="Close sources panel"
              onClick={() => setMobileSourcesOpen(false)}
            />
            <div
              className="fixed inset-y-0 right-0 z-40 h-full max-w-[85vw] shadow-[var(--glow)] md:hidden"
              role="dialog"
              aria-label="Sources"
            >
              <SourcesPanel chatId={activeChatId} dawId={activeDawId} />
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  )
}
