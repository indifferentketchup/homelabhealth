import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  getRepoStatus,
  repoSyncStreamUrl,
  syncRepo,
  updateRepoConfig,
} from '@/api/boocode.js'

const IDLE_POLL_MS = 30_000
const ACTIVE_POLL_MS = 3_000

export function useRepoSyncStatus(dawId) {
  const enabled = Boolean(dawId)
  const qc = useQueryClient()
  const esRef = useRef(null)
  const [liveProgress, setLiveProgress] = useState(null)

  const query = useQuery({
    queryKey: ['repo-sync-status', dawId],
    queryFn: () => getRepoStatus(dawId),
    enabled,
    staleTime: 0,
    refetchInterval: (q) => {
      const data = q.state.data
      if (!data) return IDLE_POLL_MS
      return data.status === 'syncing' ? ACTIVE_POLL_MS : IDLE_POLL_MS
    },
  })

  useEffect(() => {
    if (!enabled) return
    if (query.data?.status !== 'syncing') {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      return
    }
    if (esRef.current) return
    if (typeof window === 'undefined' || typeof window.EventSource !== 'function') return
    try {
      const es = new EventSource(repoSyncStreamUrl(dawId), { withCredentials: true })
      esRef.current = es
      es.onmessage = (ev) => {
        try {
          const payload = JSON.parse(ev.data)
          if (payload.event === 'progress' || payload.event === 'snapshot') {
            setLiveProgress(payload)
          } else if (payload.event === 'done') {
            setLiveProgress(null)
            qc.invalidateQueries({ queryKey: ['repo-sync-status', dawId] })
            qc.invalidateQueries({ queryKey: ['repo-tree', dawId] })
            qc.invalidateQueries({ queryKey: ['repo-stats', dawId] })
            es.close()
            esRef.current = null
          } else if (payload.event === 'error') {
            setLiveProgress(null)
            qc.invalidateQueries({ queryKey: ['repo-sync-status', dawId] })
            es.close()
            esRef.current = null
          }
        } catch {
          /* ignore malformed */
        }
      }
      es.onerror = () => {
        es.close()
        esRef.current = null
      }
    } catch {
      /* SSE unavailable — polling continues */
    }
    return () => {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
    }
  }, [dawId, enabled, query.data?.status, qc])

  const triggerSync = async () => {
    await syncRepo(dawId)
    await qc.invalidateQueries({ queryKey: ['repo-sync-status', dawId] })
  }

  const updateConfig = async (patch) => {
    const res = await updateRepoConfig(dawId, patch)
    await qc.invalidateQueries({ queryKey: ['repo-sync-status', dawId] })
    return res
  }

  return { ...query, liveProgress, triggerSync, updateConfig }
}
