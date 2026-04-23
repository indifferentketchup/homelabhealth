import { useEffect, useRef } from 'react'
import { useOutletContext, useParams } from 'react-router-dom'
import { ChatView } from '@/components/chat/ChatView.jsx'
import { MobileRightDrawer } from '@/components/layout/MobileRightDrawer.jsx'
import { useBoocodeFx } from '@/hooks/useBoocodeFx.jsx'
import { useAppStore } from '@/store/index.js'
import { RepoStatusBar } from './RepoStatusBar.jsx'
import { RepoFilesPanel } from './RepoFilesPanel.jsx'
import { RepoFilePreview } from './RepoFilePreview.jsx'
import TerminalDrawer from './TerminalDrawer.jsx'

export default function BooCodeDawWorkspace() {
  const { dawId } = useParams()
  const { mobileRightDrawer = false, setMobileRightDrawer = () => {} } = useOutletContext() ?? {}
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const prevDawIdRef = useRef(dawId ?? null)
  const { chatBgOpacity } = useBoocodeFx()

  useEffect(() => {
    if (!dawId) return
    setActiveDawId(dawId)
    if (prevDawIdRef.current && prevDawIdRef.current !== dawId) {
      setActiveChatId(null)
    }
    prevDawIdRef.current = dawId
  }, [dawId, setActiveDawId, setActiveChatId])

  // The base boocode bg (#0a0604) mixed with N% opacity — higher alpha → more
  // solid panel, lower alpha → more matrix rain bleeding through. Exposed as
  // --bg/--background via inline CSS vars on the workspace div so Tailwind
  // `bg-background` / `bg-card` on descendants (ChatView, MessageBubble, etc.)
  // inherit the rgba and don't stay opaque from applyBrandingCss's root-inline.
  const chatBg = `color-mix(in srgb, #0a0604 ${Math.round(chatBgOpacity * 100)}%, transparent)`
  const panelBg = `color-mix(in srgb, #120a06 ${Math.round(chatBgOpacity * 100)}%, transparent)`
  const cardBg = `color-mix(in srgb, #1a0e08 ${Math.round(chatBgOpacity * 100)}%, transparent)`

  return (
    <div
      className="flex h-full min-h-0 flex-1 flex-col overflow-hidden"
      style={{
        color: 'var(--text)',
        '--bg': chatBg,
        '--background': chatBg,
        '--bg-panel': panelBg,
        '--popover': panelBg,
        '--muted': panelBg,
        '--bg-card': cardBg,
        '--card': cardBg,
      }}
    >
      <RepoStatusBar dawId={dawId} />
      <div className="flex min-h-0 flex-1 flex-row overflow-hidden">
        <section className="boocode-terminal-frame flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
                 style={{ background: chatBg }}>
          <ChatView chatMode="boocode" workspaceDawId={dawId} />
        </section>
        <aside className="boocode-terminal-frame hidden w-80 shrink-0 flex-col overflow-hidden border-l md:flex"
               style={{ borderColor: 'var(--border)', background: panelBg }}>
          <RepoFilesPanel dawId={dawId} />
        </aside>
      </div>
      <TerminalDrawer dawId={dawId} />
      <RepoFilePreview dawId={dawId} />
      <MobileRightDrawer
        open={mobileRightDrawer}
        onClose={() => setMobileRightDrawer(false)}
        dawId={dawId ?? null}
      />
    </div>
  )
}
