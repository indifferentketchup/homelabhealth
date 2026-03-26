import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, Outlet } from 'react-router-dom'
import { Menu } from 'lucide-react'

import { getOllamaSettings } from '@/api/ollama.js'
import { listPersonas } from '@/api/personas.js'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { Sidebar } from '@/components/layout/Sidebar.jsx'
import { DawQuerySync } from '@/components/DawQuerySync.jsx'
import { UserProfileAvatar } from '@/components/layout/UserProfileAvatar.jsx'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import { PATH_BOOOPS } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'

import BooOpsSettings from './Settings.jsx'

export default function BooOpsApp() {
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setDefaultModel = useAppStore((s) => s.setDefaultModel)
  const hydrateUserProfile = useAppStore((s) => s.hydrateUserProfile)

  const { data: ollamaSettingsBoot } = useQuery({
    queryKey: ['ollama', 'settings', 'booops'],
    queryFn: () => getOllamaSettings('booops'),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (ollamaSettingsBoot?.default_model != null) setDefaultModel(ollamaSettingsBoot.default_model)
  }, [ollamaSettingsBoot?.default_model, setDefaultModel])

  const { data: personaPack } = useQuery({
    queryKey: ['personas', 'booops'],
    queryFn: () => listPersonas('booops'),
    staleTime: 60_000,
  })

  useEffect(() => {
    const items = personaPack?.items
    if (Array.isArray(items)) setPersonas(items)
  }, [personaPack, setPersonas])

  useEffect(() => {
    hydrateUserProfile()
  }, [hydrateUserProfile])

  return (
    <TooltipProvider>
      <DawQuerySync />
      <div className="flex h-[100dvh] w-full overflow-clip bg-background text-foreground md:flex-row">
        <Sidebar
          appMode="booops"
          routeBase={PATH_BOOOPS}
          mobileOpen={mobileSidebar}
          onMobileOpenChange={setMobileSidebar}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
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
            <ModelSelectorBar className="min-w-0 flex-1" />
            <Button type="button" variant="ghost" size="icon" className="shrink-0" asChild aria-label="Your profile">
              <Link to={`${PATH_BOOOPS}/profile`}>
                <UserProfileAvatar size="button" className="size-7 text-sm" />
              </Link>
            </Button>
          </header>
          <Link
            to={`${PATH_BOOOPS}/profile`}
            className="pointer-events-auto fixed right-3 top-3 z-40 hidden rounded-full border border-border bg-card shadow-sm md:inline-flex"
            aria-label="Your profile"
          >
            <span className="p-0.5">
              <UserProfileAvatar size="button" />
            </span>
          </Link>
          <div className="flex min-h-0 flex-1 flex-col">
            <Outlet />
          </div>
        </div>
        <BooOpsSettings />
      </div>
    </TooltipProvider>
  )
}
