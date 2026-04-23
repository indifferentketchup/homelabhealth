import { useCallback, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { ChatView } from '@/components/chat/ChatView.jsx'
import { friendlyErr } from '@/lib/friendlyErr.js'
import * as terminalsApi from '@/api/terminals.js'

import BoocodeWorkspaceHeader from './BoocodeWorkspaceHeader.jsx'
import BoocodeSplitPane from './BoocodeSplitPane.jsx'
import TerminalPanesHost from './TerminalPanesHost.jsx'

/**
 * BoocodeCenterPane
 *
 * Orchestrator for the BooCode workspace center column.
 * Owns view-mode state (primary, split, activeSessionId, splitRatio).
 * Mounts ChatView + TerminalPanesHost — BOTH are always mounted.
 * When split=false, the non-primary pane is hidden via display:none so that
 * xterm scrollback and chat scroll position survive every view-mode flip.
 *
 * Props:
 *  - dawId:    string
 *  - dawName?: string | null   — forwarded to BoocodeWorkspaceHeader
 *
 * State (local, NOT persisted, resets on dawId change):
 *  - primary:         'chat' | 'terminal'   starts at 'chat'
 *  - split:           boolean               starts at false
 *  - activeSessionId: string | null         starts at null
 *  - splitRatio:      number                starts at 0.5
 */

export default function BoocodeCenterPane({ dawId, dawName = null }) {
  const qc = useQueryClient()

  // ── View-mode state ──────────────────────────────────────────────────────
  // All four reset when dawId changes (see "adjust during render" block below).
  const [primary, setPrimary] = useState('chat')
  const [split, setSplit] = useState(false)
  const [activeSessionId, setActiveSessionId] = useState(null)
  const [splitRatio, setSplitRatio] = useState(0.5)

  // Modal open state — parent controls, so CenterPane can set primary=terminal
  // before the modal appears.
  const [showNewModal, setShowNewModal] = useState(false)

  // Toast (local state + setTimeout pattern from ChatInput.jsx)
  const [toastMsg, setToastMsg] = useState(null)

  // ── Reset view-mode when dawId changes ──────────────────────────────────
  // Uses the "adjust state when a prop changes" pattern (React docs) to avoid
  // setState inside a useEffect, which triggers an extra render cycle and can
  // cause flicker. The [lastDaw] sentinel lets us detect the change.
  const [lastDaw, setLastDaw] = useState(dawId)
  if (dawId !== lastDaw) {
    setLastDaw(dawId)
    setPrimary('chat')
    setSplit(false)
    setActiveSessionId(null)
    setSplitRatio(0.5)
    setShowNewModal(false)
  }

  // ── Toast auto-dismiss ───────────────────────────────────────────────────
  useEffect(() => {
    if (!toastMsg) return
    const t = window.setTimeout(() => setToastMsg(null), 2500)
    return () => window.clearTimeout(t)
  }, [toastMsg])

  // ── Ctrl+` keyboard toggle ───────────────────────────────────────────────
  // Flip primary when Ctrl+` is pressed outside of input/textarea/contenteditable.
  // Skip when focus is in an input/textarea/contenteditable so Ctrl+` doesn't steal typed backticks.
  const cyclePrimary = useCallback(() => {
    setPrimary((p) => (p === 'chat' ? 'terminal' : 'chat'))
  }, [])

  useEffect(() => {
    function onKey(e) {
      if (!e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key !== '`') return
      const target = e.target
      if (
        target &&
        target.tagName !== 'BODY' &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return
      }
      e.preventDefault()
      cyclePrimary()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [cyclePrimary])

  // ── Event bus ────────────────────────────────────────────────────────────
  useEffect(() => {
    function onNew(e) {
      const detail = e.detail || {}

      // If machineId is pre-filled, create the session directly without the modal.
      if (detail.machineId) {
        ;(async () => {
          try {
            const created = await terminalsApi.create({
              machineId: detail.machineId,
              dawId: detail.dawId ?? dawId ?? null,
              label: detail.label ?? null,
              startingCmd: detail.startingCmd ?? null,
            })
            await qc.invalidateQueries({ queryKey: ['terminals', dawId ?? null] })
            setActiveSessionId(created.id)
            setPrimary('terminal')
          } catch (err) {
            setToastMsg(friendlyErr(err, 'Could not create session'))
          }
        })()
        return
      }

      // No machineId → open the modal. Switch primary to terminal first so
      // the host is visible while the user fills in the form.
      setPrimary('terminal')
      setShowNewModal(true)
    }

    function onOpen(e) {
      const detail = e.detail || {}
      if (!detail.sessionId) return
      setActiveSessionId(detail.sessionId)
      setPrimary('terminal')
    }

    function onSend(e) {
      const { sessionId, text, appendNewline } = e.detail || {}
      if (!sessionId || typeof text !== 'string') return
      // Deliberately does NOT change primary or split — paste is transparent.
      ;(async () => {
        try {
          await terminalsApi.paste(sessionId, text, Boolean(appendNewline))
          setToastMsg('Sent to terminal')
        } catch (err) {
          setToastMsg(friendlyErr(err, 'Paste failed'))
        }
      })()
    }

    window.addEventListener('boocode:new-terminal', onNew)
    window.addEventListener('boocode:open-terminal', onOpen)
    window.addEventListener('boocode:send-to-terminal', onSend)
    return () => {
      window.removeEventListener('boocode:new-terminal', onNew)
      window.removeEventListener('boocode:open-terminal', onOpen)
      window.removeEventListener('boocode:send-to-terminal', onSend)
    }
  }, [dawId, qc, setToastMsg, setShowNewModal, setPrimary, setActiveSessionId])

  // ── Header callbacks ─────────────────────────────────────────────────────
  const handleToggleSplit = useCallback(() => {
    setSplit((s) => !s)
  }, [])

  // ── TerminalPanesHost callbacks ──────────────────────────────────────────
  const handleRequestNewModal = useCallback(() => {
    // Called from TerminalTabBar's + button. Set primary=terminal first so
    // the host is visible before the modal appears.
    setPrimary('terminal')
    setShowNewModal(true)
  }, [])

  const handleCloseNewModal = useCallback(() => {
    setShowNewModal(false)
  }, [])

  // ── Render ───────────────────────────────────────────────────────────────
  // Both ChatView and TerminalPanesHost are ALWAYS mounted.
  // When split=false, the inactive pane gets display:none — this preserves
  // xterm scrollback and chat scroll position across every view-mode flip.

  const chatVisible = split || primary === 'chat'
  const termVisible = split || primary === 'terminal'

  const chatNode = (
    <div
      style={{ display: chatVisible ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, flexDirection: 'column' }}
    >
      <ChatView chatMode="boocode" workspaceDawId={dawId} />
    </div>
  )

  const termNode = (
    <div
      style={{ display: termVisible ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, flexDirection: 'column' }}
    >
      <TerminalPanesHost
        dawId={dawId}
        activeSessionId={activeSessionId}
        onActiveSessionChange={setActiveSessionId}
        newModalOpen={showNewModal}
        onCloseNewModal={handleCloseNewModal}
        onRequestNewModal={handleRequestNewModal}
        onToast={setToastMsg}
      />
    </div>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <BoocodeWorkspaceHeader
        dawName={dawName}
        primary={primary}
        split={split}
        onCyclePrimary={cyclePrimary}
        onToggleSplit={handleToggleSplit}
      />

      {split ? (
        // Split mode: render both panes inside the draggable splitter.
        // The display:none wrappers above are both 'flex' in this branch, so
        // both children are fully visible.
        <BoocodeSplitPane
          ratio={splitRatio}
          onRatioChange={setSplitRatio}
          left={chatNode}
          right={termNode}
          ariaLabelLeft="Chat pane"
          ariaLabelRight="Terminal pane"
        />
      ) : (
        // Solo mode: flex container holds both children; only one is visible
        // at a time via the display:none wrapper above.
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {chatNode}
          {termNode}
        </div>
      )}

      {/* Toast notification */}
      {toastMsg ? (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-[200] max-w-sm -translate-x-1/2 rounded-md border border-border bg-popover px-4 py-2 text-center text-sm text-popover-foreground shadow-md"
        >
          {toastMsg}
        </div>
      ) : null}

      {/*
        TODO(commit-3): wire boocode:open-chat listener here when the sidebar
        dispatches it for per-DAW CHATS section clicks. Handler would set
        primary='chat' and let ChatView handle the chat activation itself.
      */}
    </div>
  )
}
