import { useCallback, useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Outlet, useNavigate } from 'react-router-dom'

import { fetchBranding } from '@/api/branding.js'
import { getOllamaSettings } from '@/api/ollama.js'
import { listPersonas } from '@/api/personas.js'
import { DawQuerySync } from '@/components/DawQuerySync.jsx'
import { TooltipProvider } from '@/components/ui/tooltip'
import { apply808notesLayoutToDom, clear808notesLayoutLiveDraft } from '@/lib/notes808Layout.js'
import { PATH_808NOTES_HOME } from '@/routes/paths.js'
import SettingsPage from '@/pages/booops/SettingsPage.jsx'
import { useAppStore } from '@/store/index.js'

import { SourcesPanel } from './SourcesPanel.jsx'

import './Notes808App.css'

/** Matches Tailwind `md` (Sidebar mobile breakpoint). */
function useBelowMd() {
  const [v, setV] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const apply = () => setV(mq.matches)
    apply()
    mq.addEventListener('change', apply)
    return () => mq.removeEventListener('change', apply)
  }, [])
  return v
}

/** @deprecated Routed DAW listing lives on the landing page; kept for deep links. */
export { default as DawsPage } from '@/pages/booops/DawsPage.jsx'

export function Notes808SettingsRoute() {
  const navigate = useNavigate()
  const activeChatId = useAppStore((s) => s.activeChatId)
  const activeDawId = useAppStore((s) => s.activeDawId)
  const isNarrow = useBelowMd()
  const closeSettings = useCallback(() => {
    clear808notesLayoutLiveDraft()
    navigate(PATH_808NOTES_HOME, { replace: true })
  }, [navigate])

  return (
    <div
      className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background md:flex-row md:items-stretch"
      role="region"
      aria-labelledby="settings-title"
    >
      <div className="flex min-h-0 min-w-0 flex-1 flex-col md:min-h-0">
        <SettingsPage mode="808notes" onClose={closeSettings} />
      </div>
      {!isNarrow && (
        <div className="hidden h-full min-h-0 shrink-0 md:flex">
          <SourcesPanel chatId={activeChatId} dawId={activeDawId} />
        </div>
      )}
    </div>
  )
}

export default function Notes808App() {
  const setPersonas = useAppStore((s) => s.setPersonas)
  const setDefaultModel = useAppStore((s) => s.setDefaultModel)

  const { data: ollamaSettingsBoot } = useQuery({
    queryKey: ['ollama', 'settings', '808notes'],
    queryFn: () => getOllamaSettings('808notes'),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (ollamaSettingsBoot?.default_model != null) setDefaultModel(ollamaSettingsBoot.default_model)
  }, [ollamaSettingsBoot?.default_model, setDefaultModel])

  const { data: personaPack } = useQuery({
    queryKey: ['personas', '808notes'],
    queryFn: () => listPersonas('808notes'),
    staleTime: 60_000,
  })

  useEffect(() => {
    const items = personaPack?.items
    if (Array.isArray(items)) setPersonas(items)
  }, [personaPack, setPersonas])

  useEffect(() => {
    const fn = () => apply808notesLayoutToDom()
    window.addEventListener('808notes-layout', fn)
    return () => window.removeEventListener('808notes-layout', fn)
  }, [])

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
        <main className="main flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <Outlet />
        </main>
      </div>
    </TooltipProvider>
  )
}
