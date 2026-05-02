import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useAppStore } from '@/store/index.js'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

/**
 * Opens a workspace from `?workspace=<uuid>` on the app root (e.g. pinned workspace in the sidebar).
 * Sets the active workspace and clears the active chat only when the query workspace **changes**,
 * so re-renders / Strict Mode cannot wipe a thread right after `createChat`.
 */
export function WorkspaceQuerySync() {
  const [searchParams] = useSearchParams()
  const workspaceParam = searchParams.get('workspace')
  const setActiveWorkspaceId = useAppStore((s) => s.setActiveWorkspaceId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const prevEffectiveWorkspaceRef = useRef(null)

  useEffect(() => {
    if (!workspaceParam || !UUID_RE.test(workspaceParam.trim())) {
      prevEffectiveWorkspaceRef.current = null
      return
    }
    const id = workspaceParam.trim()
    setActiveWorkspaceId(id)
    if (prevEffectiveWorkspaceRef.current !== id) {
      setActiveChatId(null)
      prevEffectiveWorkspaceRef.current = id
    }
  }, [workspaceParam, setActiveWorkspaceId, setActiveChatId])

  return null
}
