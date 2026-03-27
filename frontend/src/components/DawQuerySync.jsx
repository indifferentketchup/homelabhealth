import { useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useAppStore } from '@/store/index.js'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

/**
 * Opens a DAW from `?daw=<uuid>` on the app root (e.g. pinned DAW in the sidebar).
 * Sets the active DAW and clears the active chat only when the query DAW **changes**,
 * so re-renders / Strict Mode cannot wipe a thread right after `createChat`.
 */
export function DawQuerySync() {
  const [searchParams] = useSearchParams()
  const dawParam = searchParams.get('daw')
  const setActiveDawId = useAppStore((s) => s.setActiveDawId)
  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const prevEffectiveDawRef = useRef(null)

  useEffect(() => {
    if (!dawParam || !UUID_RE.test(dawParam.trim())) {
      prevEffectiveDawRef.current = null
      return
    }
    const id = dawParam.trim()
    setActiveDawId(id)
    if (prevEffectiveDawRef.current !== id) {
      setActiveChatId(null)
      prevEffectiveDawRef.current = id
    }
  }, [dawParam, setActiveDawId, setActiveChatId])

  return null
}
