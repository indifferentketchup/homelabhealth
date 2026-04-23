import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { friendlyErr } from '@/lib/friendlyErr.js'
import * as terminalsApi from '@/api/terminals.js'

import NewTerminalModal from './NewTerminalModal.jsx'
import TerminalPane from './TerminalPane.jsx'
import TerminalTabBar from './TerminalTabBar.jsx'

const POLL_MS = 15_000

/**
 * TerminalPanesHost
 *
 * Lifted from TerminalDrawer — owns session fetching, sorting, tab state,
 * and the keep-alive TerminalPane grid. Does NOT own the drawer chrome,
 * open/collapse state, height persistence, or Ctrl+` handling — those belong
 * to BoocodeCenterPane / the workspace layout.
 *
 * Design choice: the parent (BoocodeCenterPane) controls NewTerminalModal
 * visibility via `newModalOpen` / `onCloseNewModal` / `onRequestNewModal`.
 * This lets the center pane enforce auto-switch rules (primary='terminal')
 * before the modal opens when the user clicks "+".
 *
 * Props:
 *  - dawId:                 string | null
 *  - activeSessionId:       string | null      — controlled; hoisted to CenterPane
 *  - onActiveSessionChange: (id: string | null) => void
 *  - newModalOpen:          boolean            — parent controls modal visibility
 *  - onCloseNewModal:       () => void
 *  - onRequestNewModal:     () => void         — called when the + tab-bar button is clicked
 *  - onToast:               (msg: string) => void
 */

export default function TerminalPanesHost({
  dawId,
  activeSessionId,
  onActiveSessionChange,
  newModalOpen,
  onCloseNewModal,
  onRequestNewModal,
  onToast,
}) {
  const qc = useQueryClient()

  const { data } = useQuery({
    queryKey: ['terminals', dawId ?? null],
    queryFn: () => terminalsApi.list({ dawId }),
    staleTime: 5_000,
    refetchInterval: POLL_MS,
  })

  const sessions = useMemo(() => {
    const rows = Array.isArray(data?.active) ? data.active : []
    return rows.slice().sort((a, b) => {
      if (a.pinned !== b.pinned) return a.pinned ? -1 : 1
      return (a.created_at || '').localeCompare(b.created_at || '')
    })
  }, [data])

  // Effective active tab: controlled prop if still in the session list, else
  // fall back to the first tab. Uses the "adjust state during render" pattern
  // (React docs) to avoid setState-in-effect.
  const effectiveActiveId = useMemo(() => {
    if (sessions.length === 0) return null
    if (activeSessionId && sessions.some((s) => s.id === activeSessionId)) {
      return activeSessionId
    }
    return sessions[0]?.id ?? null
  }, [sessions, activeSessionId])

  const [lastEffectiveId, setLastEffectiveId] = useState(effectiveActiveId)
  if (effectiveActiveId !== lastEffectiveId) {
    setLastEffectiveId(effectiveActiveId)
    if (effectiveActiveId !== activeSessionId) {
      onActiveSessionChange(effectiveActiveId)
    }
  }

  const invalidateSessions = useCallback(
    () => qc.invalidateQueries({ queryKey: ['terminals', dawId ?? null] }),
    [qc, dawId],
  )

  const handleEvicted = useCallback(async () => {
    await invalidateSessions()
    onToast('Terminal session was evicted')
  }, [invalidateSessions, onToast])

  const handleRename = useCallback(
    async (sid, label) => {
      try {
        await terminalsApi.patch(sid, { label })
        await invalidateSessions()
      } catch (e) {
        onToast(friendlyErr(e, 'Rename failed'))
      }
    },
    [invalidateSessions, onToast],
  )

  const handlePin = useCallback(
    async (sid, pinned) => {
      try {
        await terminalsApi.patch(sid, { pinned })
        await invalidateSessions()
      } catch (e) {
        onToast(friendlyErr(e, pinned ? 'Pin failed' : 'Unpin failed'))
      }
    },
    [invalidateSessions, onToast],
  )

  const handleClose = useCallback(
    async (sid) => {
      try {
        await terminalsApi.del(sid)
        await invalidateSessions()
      } catch (e) {
        onToast(friendlyErr(e, 'Close failed'))
      }
    },
    [invalidateSessions, onToast],
  )

  const handleCreated = useCallback(
    async (session) => {
      await invalidateSessions()
      if (session?.id) onActiveSessionChange(session.id)
      onCloseNewModal()
    },
    [invalidateSessions, onActiveSessionChange, onCloseNewModal],
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <TerminalTabBar
        sessions={sessions}
        activeSessionId={effectiveActiveId}
        onActivate={onActiveSessionChange}
        onNew={onRequestNewModal}
        onRename={handleRename}
        onPin={handlePin}
        onClose={handleClose}
      />

      <div className="relative flex min-h-0 flex-1 overflow-hidden">
        {sessions.length === 0 ? (
          <div
            className="flex h-full w-full items-center justify-center p-6 text-center text-xs"
            style={{ color: 'var(--text-dim)', fontFamily: "'JetBrains Mono', monospace" }}
          >
            No terminal sessions. Click + to start one.
          </div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className="absolute inset-0"
              style={{ display: s.id === effectiveActiveId ? 'block' : 'none' }}
            >
              <TerminalPane
                sessionId={s.id}
                visible={s.id === effectiveActiveId}
                onEvicted={handleEvicted}
              />
            </div>
          ))
        )}
      </div>

      {newModalOpen ? (
        <NewTerminalModal
          dawId={dawId}
          onClose={onCloseNewModal}
          onCreated={handleCreated}
          onError={(msg) => onToast(msg)}
        />
      ) : null}
    </div>
  )
}
