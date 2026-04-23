import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useNavigate } from 'react-router-dom'
import { FolderOpen, Loader2, Menu } from 'lucide-react'

import { fetchBranding } from '@/api/branding.js'
import { getOllamaSettings } from '@/api/ollama.js'
import { listPersonas } from '@/api/personas.js'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { DawQuerySync } from '@/components/DawQuerySync.jsx'
import CRTOverlay from '@/components/fx/CRTOverlay.jsx'
import MatrixRain from '@/components/fx/MatrixRain.jsx'
import { Sidebar } from '@/components/layout/Sidebar.jsx'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'
import {
  FxSuppressProvider,
  useBoocodeFx,
  useFxSuppress,
  useFxSuppressState,
} from '@/hooks/useBoocodeFx.jsx'
import SettingsPage from '@/pages/booops/SettingsPage.jsx'
import BooCodeCommandPalette from '@/pages/boocode/BooCodeCommandPalette.jsx'
import { PATH_BOOCODE, PATH_BOOCODE_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'

export function BooCodeSettingsRoute() {
  const navigate = useNavigate()
  const closeSettings = useCallback(() => {
    navigate(PATH_BOOCODE_HOME, { replace: true })
  }, [navigate])

  useFxSuppress({ matrix: true, crt: true })

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background"
      role="region"
      aria-labelledby="settings-title"
    >
      <SettingsPage mode="boocode" onClose={closeSettings} />
    </div>
  )
}

function BooCodeShell({ mobileSidebar, setMobileSidebar, mobileRightDrawer, setMobileRightDrawer }) {
  const { matrixEnabled, crtEnabled, density, speed, matrixOpacity, crtOpacity } = useBoocodeFx()
  const { suppressMatrix, suppressCrt } = useFxSuppressState()
  const activeDawId = useAppStore((s) => s.activeDawId)

  const showMatrix = matrixEnabled && !suppressMatrix
  const showCrt = crtEnabled && !suppressCrt

  return (
    <>
      {showMatrix ? <MatrixRain density={density} speed={speed} opacity={matrixOpacity} /> : null}
      {showCrt ? <CRTOverlay opacity={crtOpacity} /> : null}
      <div
        className="layout flex h-[100dvh] w-full overflow-clip text-foreground md:flex-row"
        data-mode="boocode"
        style={{ position: 'relative', zIndex: 10 }}
      >
        <Sidebar
          appMode="boocode"
          routeBase={PATH_BOOCODE}
          mobileOpen={mobileSidebar}
          onMobileOpenChange={setMobileSidebar}
        />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex min-w-0 items-center gap-2 border-b border-border bg-background px-2 py-2 md:hidden">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-11 w-11 md:h-9 md:w-9"
              aria-label="Open sidebar"
              onClick={() => setMobileSidebar(true)}
            >
              <Menu className="size-5" />
            </Button>
            <ModelSelectorBar className="min-w-0 flex-1" />
            {activeDawId ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="ml-auto h-11 w-11 md:h-9 md:w-9"
                aria-label="Repo files"
                onClick={() => setMobileRightDrawer(true)}
              >
                <FolderOpen className="size-5" />
              </Button>
            ) : null}
          </header>
          <main className="main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <Outlet context={{ mobileRightDrawer, setMobileRightDrawer }} />
          </main>
        </div>
      </div>
    </>
  )
}

export default function BooCodeApp() {
  const [mobileSidebar, setMobileSidebar] = useState(false)
  const [mobileRightDrawer, setMobileRightDrawer] = useState(false)
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setDefaultModel = useAppStore((s) => s.setDefaultModel)
  const hydrateUserProfile = useAppStore((s) => s.hydrateUserProfile)

  // Phase 1: BooCode reuses 'booops' for ollama settings until its own keys land.
  const { data: ollamaSettingsBoot } = useQuery({
    queryKey: ['ollama', 'settings', 'boocode'],
    queryFn: () => getOllamaSettings('boocode'),
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

  const { isPending: brandingPending } = useQuery({
    queryKey: ['branding', 'boocode'],
    queryFn: () => fetchBranding('boocode'),
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
    <FxSuppressProvider>
      <TooltipProvider>
        <DawQuerySync />
        <BooCodeCommandPalette />
        <BooCodeShell
          mobileSidebar={mobileSidebar}
          setMobileSidebar={setMobileSidebar}
          mobileRightDrawer={mobileRightDrawer}
          setMobileRightDrawer={setMobileRightDrawer}
        />
      </TooltipProvider>
    </FxSuppressProvider>
  )
}
