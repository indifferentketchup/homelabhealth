import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet, matchPath, useLocation, useNavigate } from 'react-router-dom'
import { FileStack, Loader2, Menu } from 'lucide-react'

import { fetchBranding } from '@/api/branding.js'
import { getModelSettings } from '@/api/inference.js'
import { listPersonas } from '@/api/personas.js'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { WorkspaceQuerySync } from '@/components/WorkspaceQuerySync.jsx'
import { Sidebar } from '@/components/layout/Sidebar.jsx'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { applyWorkspaceLayoutToDom, clearWorkspaceLayoutLiveDraft } from '@/lib/workspaceLayout.js'
import { PATH_HOME, workspacePath } from '@/routes/paths.js'
import SettingsPage from '@/pages/workspace/SettingsPage.jsx'
import { useAppStore } from '@/store/index.js'

import { SourcesPanel } from './SourcesPanel.jsx'

import './WorkspaceApp.css'

export function SettingsRoute() {
  const navigate = useNavigate()
  const closeSettings = useCallback(() => {
    clearWorkspaceLayoutLiveDraft()
    navigate(PATH_HOME, { replace: true })
  }, [navigate])

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background md:min-h-0"
      role="region"
      aria-labelledby="settings-title"
    >
      <SettingsPage onClose={closeSettings} />
    </div>
  )
}

export default function WorkspaceApp() {
  const location = useLocation()
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [mobileSourcesOpen, setMobileSourcesOpen] = useState(false)
  const activeChatId = useAppStore((s) => s.activeChatId)
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId)
  const branding = useAppStore((s) => s.branding)
  const sourcesRailW = branding?.sidebarWidth ?? 260
  const setActiveWorkspaceId = useAppStore((s) => s.setActiveWorkspaceId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setDefaultModel = useAppStore((s) => s.setDefaultModel)
  const hydrateUserProfile = useAppStore((s) => s.hydrateUserProfile)

  const { aiPath, settingsPath } = useMemo(
    () => ({
      aiPath: '/ai',
      settingsPath: '/settings',
    }),
    [],
  )

  const isLanding = Boolean(matchPath({ path: PATH_HOME, end: true }, location.pathname))

  useEffect(() => {
    if (!isLanding) return
    setActiveWorkspaceId(null)
    setActiveChatId(null)
  }, [isLanding, setActiveWorkspaceId, setActiveChatId])

  const isAuxRoute = Boolean(
    matchPath({ path: aiPath, end: true }, location.pathname) ||
      matchPath({ path: settingsPath, end: true }, location.pathname),
  )
  const onWorkspaceSourcesPage = /\/sources\/?$/.test(location.pathname)
  const showWorkspaceSourcesShortcut =
    !isLanding && !isAuxRoute && Boolean(activeWorkspaceId) && !onWorkspaceSourcesPage

  const { data: modelSettingsBoot } = useQuery({
    queryKey: ['inference', 'settings'],
    queryFn: () => getModelSettings(),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (modelSettingsBoot?.default_model != null) setDefaultModel(modelSettingsBoot.default_model)
  }, [modelSettingsBoot?.default_model, setDefaultModel])

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
    const fn = () => applyWorkspaceLayoutToDom()
    window.addEventListener('workspace-layout', fn)
    return () => window.removeEventListener('workspace-layout', fn)
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
    queryKey: ['branding'],
    queryFn: () => fetchBranding(),
    staleTime: 60_000,
    retry: false,
  })

  if (brandingPending) {
    return (
      <div className="flex min-h-[100dvh] items-center justify-center gap-2 bg-background text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading…
      </div>
    )
  }

  return (
    <TooltipProvider>
      <WorkspaceQuerySync />
      <div className="layout flex h-[100lvh] w-full overflow-clip bg-background text-foreground md:flex-row">
        <Sidebar
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
            ) : showWorkspaceSourcesShortcut ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                asChild
                aria-label="Sources"
              >
                <Link
                  to={workspacePath(activeWorkspaceId, 'sources')}
                  onClick={() => setMobileSourcesOpen(false)}
                >
                  <FileStack className="size-5" />
                </Link>
              </Button>
            ) : null}
          </header>
          <main
            className="main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
            style={{ paddingBottom: 'var(--bc-keyboard-pad, 0px)' }}
          >
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
              style={{ width: `min(85vw, ${sourcesRailW}px)` }}
              role="dialog"
              aria-label="Sources mobile"
            >
              <SourcesPanel chatId={activeChatId} workspaceId={activeWorkspaceId} />
            </div>
          </>
        )}
      </div>
    </TooltipProvider>
  )
}
