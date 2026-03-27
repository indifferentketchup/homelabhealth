import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'

import { adminSetUserPassword, createUser, deleteUser, listUsers } from '@/api/users.js'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { cn } from '@/lib/utils.js'
import { useAppStore } from '@/store/index.js'

function RoleBadge({ role }) {
  const privileged = role === 'owner' || role === 'super_admin'
  return (
    <span
      className={cn(
        'rounded px-1.5 py-0.5 text-xs font-medium',
        privileged ? 'bg-accent/15 text-accent' : 'bg-muted text-muted-foreground',
      )}
    >
      {role}
    </span>
  )
}

export default function UserAdminTab() {
  const queryClient = useQueryClient()
  const currentUser = useAppStore((s) => s.currentUser)
  const meId = currentUser?.user_id != null ? String(currentUser.user_id) : null

  const [newUsername, setNewUsername] = useState('')
  const [newMemberPassword, setNewMemberPassword] = useState('')
  const [createBusy, setCreateBusy] = useState(false)
  const [createMsg, setCreateMsg] = useState(null)
  const [createErr, setCreateErr] = useState(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['users', 'admin-list'],
    queryFn: listUsers,
  })

  const [pwByUser, setPwByUser] = useState(() => ({}))
  const [busyPwUserId, setBusyPwUserId] = useState(null)
  const [pwMsg, setPwMsg] = useState(null)
  const [pwOpenId, setPwOpenId] = useState(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState(null)
  const [deleteBusyId, setDeleteBusyId] = useState(null)
  const [deleteErr, setDeleteErr] = useState(null)

  async function onCreateMember() {
    setCreateMsg(null)
    setCreateErr(null)
    const u = newUsername.trim()
    const p = newMemberPassword.trim()
    if (!u) {
      setCreateErr('Username is required.')
      return
    }
    if (p.length < 8) {
      setCreateErr('Password must be at least 8 characters.')
      return
    }
    setCreateBusy(true)
    try {
      await createUser(u, p)
      setNewUsername('')
      setNewMemberPassword('')
      setCreateMsg('Member created.')
      await queryClient.invalidateQueries({ queryKey: ['users', 'admin-list'] })
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e)
      if (m.includes('username_taken')) setCreateErr('Username already taken.')
      else setCreateErr(m)
    } finally {
      setCreateBusy(false)
    }
  }

  async function resetPassword(userId) {
    const pw = (pwByUser[userId] || '').trim()
    if (!pw || pw.length < 8) {
      setPwMsg('Password must be at least 8 characters.')
      return
    }
    setBusyPwUserId(userId)
    setPwMsg(null)
    try {
      await adminSetUserPassword(userId, pw)
      setPwByUser((s) => ({ ...s, [userId]: '' }))
      setPwMsg('Password updated.')
      await queryClient.invalidateQueries({ queryKey: ['users', 'admin-list'] })
    } catch (e) {
      setPwMsg(e instanceof Error ? e.message : 'Failed to update password.')
    } finally {
      setBusyPwUserId(null)
    }
  }

  async function confirmDelete(userId) {
    setDeleteErr(null)
    setDeleteBusyId(userId)
    try {
      await deleteUser(userId)
      setDeleteConfirmId(null)
      await queryClient.invalidateQueries({ queryKey: ['users', 'admin-list'] })
    } catch (e) {
      setDeleteErr(e instanceof Error ? e.message : 'Delete failed.')
    } finally {
      setDeleteBusyId(null)
    }
  }

  if (isLoading) {
    return <p className="fs-nav text-sm text-muted-foreground">Loading users…</p>
  }
  if (error) {
    return <p className="fs-nav text-sm text-destructive">Could not load users.</p>
  }

  const items = Array.isArray(data?.items) ? data.items : []

  return (
    <section className="mx-auto w-full max-w-2xl space-y-6">
      <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Users</h2>
      <p className="fs-nav text-sm text-muted-foreground">
        Create members, remove accounts, or set a new password. Members sign in with the username and password you
        assign.
      </p>

      <div className="space-y-3 rounded-lg border border-border p-4">
        <h3 className="fs-nav text-sm font-semibold text-foreground">Create member</h3>
        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Username</span>
            <input
              type="text"
              autoComplete="off"
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              className="fs-input h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
          <label className="flex min-w-[10rem] flex-1 flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Password (min 8)</span>
            <input
              type="password"
              autoComplete="new-password"
              value={newMemberPassword}
              onChange={(e) => setNewMemberPassword(e.target.value)}
              className="fs-input h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
          <Button type="button" size="sm" disabled={createBusy} onClick={() => void onCreateMember()}>
            {createBusy ? 'Creating…' : 'Create member'}
          </Button>
        </div>
        {createMsg ? <p className="text-sm text-foreground">{createMsg}</p> : null}
        {createErr ? <p className="text-sm text-destructive">{createErr}</p> : null}
      </div>

      {deleteErr ? <p className="text-sm text-destructive">{deleteErr}</p> : null}
      {pwMsg ? <p className="text-sm text-foreground">{pwMsg}</p> : null}

      <ScrollArea className="max-h-[min(32rem,55vh)] pr-3">
        <ul className="space-y-3">
          {items.map((u) => {
            const idStr = String(u.id)
            const isSelf = meId != null && idStr === meId
            const pwOpen = pwOpenId === idStr
            return (
              <li key={u.id} className="rounded-lg border border-border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="min-w-0 flex-1 text-sm font-medium text-foreground">
                    <span className="truncate">{u.display_name}</span>{' '}
                    <span className="font-normal text-muted-foreground">(@{u.username})</span>
                  </div>
                  <RoleBadge role={u.role} />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="fs-nav shrink-0 gap-1"
                    onClick={() => setPwOpenId((cur) => (cur === idStr ? null : idStr))}
                  >
                    {pwOpen ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                    Password
                  </Button>
                  {!isSelf ? (
                    deleteConfirmId === idStr ? (
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-sm text-destructive">Sure?</span>
                        <Button
                          type="button"
                          size="sm"
                          variant="destructive"
                          disabled={deleteBusyId === idStr}
                          onClick={() => void confirmDelete(u.id)}
                        >
                          {deleteBusyId === idStr ? 'Deleting…' : 'Yes'}
                        </Button>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={deleteBusyId === idStr}
                          onClick={() => setDeleteConfirmId(null)}
                        >
                          Cancel
                        </Button>
                      </span>
                    ) : (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="text-destructive hover:text-destructive"
                        aria-label={`Delete ${u.username}`}
                        onClick={() => {
                          setDeleteConfirmId(idStr)
                          setDeleteErr(null)
                        }}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    )
                  ) : null}
                </div>
                {pwOpen ? (
                  <div className="mt-4 flex flex-wrap items-end gap-2 border-t border-border pt-4">
                    <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-xs">
                      <span className="text-muted-foreground">New password</span>
                      <input
                        type="password"
                        autoComplete="new-password"
                        value={pwByUser[u.id] || ''}
                        onChange={(e) => setPwByUser((s) => ({ ...s, [u.id]: e.target.value }))}
                        className="fs-input h-9 rounded-md border border-border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      />
                    </label>
                    <Button
                      type="button"
                      size="sm"
                      disabled={busyPwUserId === u.id}
                      onClick={() => void resetPassword(u.id)}
                    >
                      {busyPwUserId === u.id ? 'Saving…' : 'Update password'}
                    </Button>
                  </div>
                ) : null}
              </li>
            )
          })}
        </ul>
      </ScrollArea>
    </section>
  )
}
