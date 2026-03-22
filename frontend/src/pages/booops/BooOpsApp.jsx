import { useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Menu } from 'lucide-react'

import { ChatView } from '@/components/chat/ChatView.jsx'
import { Sidebar } from '@/components/layout/Sidebar.jsx'
import { Button } from '@/components/ui/button'
import { TooltipProvider } from '@/components/ui/tooltip'

import AllChats from './AllChats.jsx'

export default function BooOpsApp() {
  const [mobileSidebar, setMobileSidebar] = useState(false)

  return (
    <TooltipProvider>
      <div className="flex h-[100dvh] w-full overflow-hidden bg-background text-foreground md:flex-row">
        <Sidebar mobileOpen={mobileSidebar} onMobileOpenChange={setMobileSidebar} />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <header className="flex items-center gap-2 border-b border-border bg-background px-2 py-2 md:hidden">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Open sidebar"
              onClick={() => setMobileSidebar(true)}
            >
              <Menu className="size-5" />
            </Button>
            <span className="text-sm font-semibold tracking-wide">BooOps</span>
          </header>
          <div className="flex min-h-0 flex-1 flex-col">
            <Routes>
              <Route path="/" element={<ChatView />} />
              <Route path="/chats" element={<AllChats />} />
            </Routes>
          </div>
        </div>
      </div>
    </TooltipProvider>
  )
}
