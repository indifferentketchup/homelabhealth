import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { adminSetUserPassword, listUsers } from '@/api/users.js'
import { Button } from '@/components/ui/button'

export default function UserAdminTab() {
  const queryClient = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ['users', 'admin-list'],
    queryFn: listUsers,
  })
  const [pwByUser, setPwByUser] = useState(() => ({}))
  const [busyId, setBusyId] = useState(null)
  const [msg, setMsg] = useState(null)

  async function resetPassword(userId) {
    const pw = (pwByUser[userId] || '').trim()
    if (!pw || pw.length < 8) {
      setMsg('Password must be at least 8 characters.')
      return
    }
    setBusyId(userId)
    setMsg(null)
    try {
      await adminSetUserPassword(userId, pw)
      setPwByUser((s) => ({ ...s, [userId]: '' }))
      setMsg('Password updated.')
      await queryClient.invalidateQueries({ queryKey: ['users', 'admin-list'] })
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'Failed to update password.')
    } finally {
      setBusyId(null)
    }
  }

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading users…</p>
  if (error) return <p className="text-sm text-destructive">Could not load users.</p>

  const items = Array.isArray(data?.items) ? data.items : []

  return (
    <section className="mx-auto w-full max-w-2xl space-y-4">
      <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Users</h2>
      <p className="text-sm text-muted-foreground">
        Set a new password for any database account. They sign in with the new password immediately.
      </p>
      {msg ? <p className="text-sm text-foreground">{msg}</p> : null}
      <ul className="space-y-4">
        {items.map((u) => (
          <li key={u.id} className="rounded-lg border border-border p-4">
            <div className="mb-2 text-sm font-medium text-foreground">
              {u.display_name}{' '}
              <span className="font-normal text-muted-foreground">(@{u.username})</span>
              <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{u.role}</span>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-xs">
                <span className="text-muted-foreground">New password</span>
                <input
                  type="password"
                  autoComplete="new-password"
                  value={pwByUser[u.id] || ''}
                  onChange={(e) => setPwByUser((s) => ({ ...s, [u.id]: e.target.value }))}
                  className="h-9 rounded-md border border-border bg-background px-2 text-sm text-foreground outline-none ring-ring focus-visible:ring-2"
                />
              </label>
              <Button type="button" size="sm" disabled={busyId === u.id} onClick={() => void resetPassword(u.id)}>
                {busyId === u.id ? 'Saving…' : 'Update password'}
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
