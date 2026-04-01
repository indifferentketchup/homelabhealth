import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { getDaw } from '@/api/daws.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { ModelSelectorBar } from '@/components/chat/ModelSelectorBar.jsx'
import { FileViewerPanel } from '@/components/chat/FileViewerPanel.jsx'
import { FileBrowserPanel } from '@/components/FileBrowserPanel.jsx'
import { UserProfileMenu } from '@/components/layout/UserProfileMenu.jsx'
import { PATH_BOOOPS, PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'

export function BooOpsDawChat() {
  const { dawId } = useParams()
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const branding = useAppStore((s) => s.branding)
  const prevDawIdRef = useRef(null)

  const [viewerFile, setViewerFile] = useState(null)

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
        {viewerFile ? (
          <div className="hidden h-full min-h-0 w-[min(100%,420px)] min-w-[280px] max-w-[420px] shrink-0 flex-col border-l border-sidebar-border bg-sidebar text-sidebar-foreground md:flex">
            <FileViewerPanel
              file={viewerFile}
              onClose={() => setViewerFile(null)}
              onAttachLines={({ filename, content }) => {
                window.dispatchEvent(
                  new CustomEvent('boolab:attach-chat-file', { detail: { filename, content } }),
                )
              }}
            />
          </div>
        ) : (
          <FileBrowserPanel
            variant="dock"
            isOpen={true}
            onClose={() => {}}
            rootPath={dawSyncFolder || undefined}
            onFileSelect={(filename, path, content) => {
              window.dispatchEvent(
                new CustomEvent('boolab:attach-chat-file', { detail: { filename, content } }),
              )
              setViewerFile({ filename, path })
            }}
          />
        )}
      </div>
    </div>
  )
}