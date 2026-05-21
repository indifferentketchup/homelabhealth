import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { getSystemProfile } from '@/api/system.js'

/**
 * First-boot gate. Wraps the post-login route tree.
 *
 * Behavior:
 *   - While `GET /api/system/profile` is in flight, render the child via
 *     <Outlet /> (do NOT redirect during loading — accept a one-frame flicker
 *     on resolve rather than a spinner on every navigation).
 *   - When the query resolves with `setup_complete === false` AND the current
 *     path is not /settings, redirect to /settings?tab=system. Path exclusion
 *     is load-bearing — without it, the gate creates a redirect loop on the
 *     wizard page itself.
 *   - In every other case (setup_complete true, query failed, undefined),
 *     render the child route.
 *
 * Mounted in AppRoutes.jsx as a layout route around the "/" tree. Phase 1+
 * setup logic (model download progress, post-pull validation, etc.) can
 * extend this single point.
 *
 * Cache: shares the queryKey `['system', 'profile']` with SystemTab, which
 * calls `setQueryData` on save/redetect so the gate sees the new state
 * without a refetch delay.
 */
export default function RequireSetup() {
  const location = useLocation()
  const { data, isLoading } = useQuery({
    queryKey: ['system', 'profile'],
    queryFn: getSystemProfile,
    staleTime: 30_000,
    // Don't retry on errors here; we'd rather fall through and let the user
    // proceed than block the whole app on a transient backend hiccup.
    retry: false,
  })

  if (isLoading) {
    return <Outlet />
  }

  const needsSetup = data?.setup_complete === false
  const onSettings = location.pathname === '/settings'

  if (needsSetup && !onSettings) {
    return <Navigate to="/settings?tab=system" replace />
  }

  return <Outlet />
}
