import { useParams } from 'react-router-dom'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { RepoStatusBar } from './RepoStatusBar.jsx'
import { RepoFilesPanel } from './RepoFilesPanel.jsx'
import { RepoFilePreview } from './RepoFilePreview.jsx'

export default function BooCodeDawWorkspace() {
  const { dawId } = useParams()
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col overflow-hidden"
         style={{ color: 'var(--text)' }}>
      <RepoStatusBar dawId={dawId} />
      <div className="flex min-h-0 flex-1 flex-row overflow-hidden">
        <section className="boocode-terminal-frame flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
                 style={{ background: 'var(--bg)' }}>
          <ChatView chatMode="boocode" workspaceDawId={dawId} />
        </section>
        <aside className="boocode-terminal-frame hidden w-80 shrink-0 flex-col overflow-hidden border-l md:flex"
               style={{ borderColor: 'var(--border)', background: 'var(--bg-panel)' }}>
          <RepoFilesPanel dawId={dawId} />
        </aside>
      </div>
      <RepoFilePreview dawId={dawId} />
    </div>
  )
}
