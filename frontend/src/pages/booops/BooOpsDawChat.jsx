import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { FolderOpen } from 'lucide-react'

import { getDaw } from '@/api/daws.js'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { FileViewerPanel } from '@/components/chat/FileViewerPanel.jsx'
import { FileBrowserPanel } from '@/components/FileBrowserPanel.jsx'
import { Button } from '@/components/ui/button'
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
    <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="flex min-h-0 min-w-0 flex-1">
        <ChatView chatMode="booops" workspaceDawId={dawId} />
      </div>
      <div
        className="hidden h-full min-h-0 shrink-0 flex-col md:flex"
        style={{ width: sidebarW }}
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
          <div className="flex shrink-0 items-center justify-end gap-1 border-b border-sidebar-border bg-sidebar px-1 py-1">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="fs-nav h-8 gap-1 px-2"
              onClick={() => setFileBrowseOpen(true)}
            >
              <FolderOpen className="size-4" />
              Browse files
            </Button>
          </div>
        )}
        <FileBrowserPanel
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
