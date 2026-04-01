import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { ChevronRight, FolderOpen, PanelRight } from 'lucide-react'

import { getDaw } from '@/api/daws.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { FileViewerPanel } from '@/components/chat/FileViewerPanel.jsx'
import { FileBrowserPanel } from '@/components/FileBrowserPanel.jsx'
import { UserProfileMenu } from '@/components/layout/UserProfileMenu.jsx'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { PATH_BOOOPS, PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'

export function BooOpsDawChat() {
  const { dawId } = useParams()
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const branding = useAppStore((s) => s.branding)
  const sidebarW = branding?.sidebarWidth ?? 260
  const prevDawIdRef = useRef(null)

  const [viewerFile, setViewerFile] = useState(null)
  const [fileBrowseOpen, setFileBrowseOpen] = useState(false)
  const [filesPanelExpanded, setFilesPanelExpanded] = useState(true)
  const filesRailCollapsed = !filesPanelExpanded && !viewerFile

  const { data: workspaceDaw } = useQuery({
    queryKey: ['daws', dawId],
    queryFn: () => getDaw(dawId),
    enabled: Boolean(dawId),
    staleTime: 60_000,
  })
  const dawSyncFolder = workspaceDaw?.dubdrive_sync_folder || undefined

  useEffect(() => {
    if (!dawId) return
    setActiveDawId(dawId)
    if (prevDawIdRef.current !== dawId) {
      setActiveChatId(null)
      prevDawIdRef.current = dawId
    }
  }, [dawId, setActiveDawId, setActiveChatId])

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <div className="hidden shrink-0 items-center gap-2 border-b border-border bg-background px-2 py-2 md:flex">
        <ModelSelectorBar className="min-w-0 flex-1" />
        <UserProfileMenu
          profilePath={`${PATH_BOOOPS}/profile`}
          homePath={PATH_BOOOPS_HOME}
          placement="header"
        />
      </div>
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <div className="flex min-h-0 min-w-0 flex-1">
          <ChatView chatMode="booops" workspaceDawId={dawId} hideDesktopModelBar />
        </div>
        <div
          className={cn(
            'hidden h-full min-h-0 shrink-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground transition-[width] duration-200 ease-out md:flex',
            filesRailCollapsed && 'w-14',
          )}
          style={!filesRailCollapsed ? { width: sidebarW } : undefined}
        >
          {viewerFile ? (
            <FileViewerPanel
              file={viewerFile}
              onClose={() => setViewerFile(null)}
              onAttachLines={({ filename, content }) => {
                window.dispatchEvent(
                  new CustomEvent('boolab:attach-chat-file', { detail: { filename, content } }),
                )
              }}
            />
          ) : (
            <div className="flex shrink-0 flex-col gap-2 border-b border-sidebar-border p-2">
              <Button
                type="button"
                variant="outline"
                size="icon"
                className={cn(
                  'h-9 w-9 shrink-0 border-sidebar-border bg-card text-foreground hover:bg-sidebar-accent',
                  filesRailCollapsed ? 'mx-auto' : 'self-end',
                )}
                onClick={() => setFilesPanelExpanded((v) => !v)}
                aria-label={filesRailCollapsed ? 'Expand files panel' : 'Collapse files panel'}
              >
                {filesRailCollapsed ? <PanelRight className="size-4" /> : <ChevronRight className="size-4" />}
              </Button>
              <Button
                type="button"
                variant="secondary"
                size={filesRailCollapsed ? 'icon' : 'sm'}
                className={cn(
                  'fs-nav shrink-0 border-sidebar-border',
                  filesRailCollapsed ? 'mx-auto h-9 w-9' : 'h-9 w-full justify-start gap-2 px-2',
                )}
                onClick={() => setFileBrowseOpen(true)}
                aria-label="Browse files"
              >
                <FolderOpen className="size-4 shrink-0" />
                {!filesRailCollapsed ? <span>Browse files</span> : null}
              </Button>
            </div>
          )}
        </div>
        <FileBrowserPanel
          variant="dock"
          isOpen={fileBrowseOpen}
          onClose={() => setFileBrowseOpen(false)}
          rootPath={dawSyncFolder || undefined}
          onFileSelect={(filename, path, content) => {
            window.dispatchEvent(
              new CustomEvent('boolab:attach-chat-file', { detail: { filename, content } }),
            )
            setViewerFile({ filename, path })
            setFileBrowseOpen(false)
          }}
        />
      </div>
    </div>
  )
}
