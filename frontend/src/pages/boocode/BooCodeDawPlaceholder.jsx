import { Files } from 'lucide-react'

import { ChatView } from '@/components/chat/ChatView.jsx'

export default function BooCodeDawPlaceholder() {
  return (
    <div
      className="flex h-full min-h-0 flex-1 flex-col overflow-hidden"
      style={{ color: 'var(--text)' }}
    >
      <header
        className="flex shrink-0 items-center gap-3 border-b px-4 py-2"
        style={{ borderColor: 'var(--border)', background: 'var(--bg-panel)' }}
      >
        <div className="boocode-breadcrumb">BOOCODE@TERMINAL ~/project</div>
      </header>
      <div className="flex min-h-0 flex-1 flex-row overflow-hidden">
        <section
          className="boocode-terminal-frame flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden"
          style={{ background: 'var(--bg)' }}
        >
          <ChatView chatMode="boocode" />
        </section>
        <aside
          className="boocode-terminal-frame hidden w-72 shrink-0 flex-col items-center justify-center gap-3 border-l p-6 text-center md:flex"
          style={{
            borderColor: 'var(--border)',
            background: 'var(--bg-panel)',
            color: 'var(--text-dim)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          <Files className="size-6" style={{ color: 'var(--text-muted)' }} />
          <div className="text-sm">Files panel</div>
          <div className="text-xs">Coming in Phase 3</div>
        </aside>
      </div>
    </div>
  )
}
