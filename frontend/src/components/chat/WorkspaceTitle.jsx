import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import { listWorkspaces } from '@/api/workspaces.js'
import { getChat } from '@/api/chats.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

export function WorkspaceTitle({ className, variant = 'bar' }) {
  const activeChatId = useAppStore((s) => s.activeChatId)
  const storeWorkspaceId = useAppStore((s) => s.activeWorkspaceId)

  const { data: chat } = useQuery({
    queryKey: ['chat', activeChatId],
    queryFn: () => getChat(activeChatId),
    enabled: Boolean(activeChatId),
  })

  const { data: workspacePack } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => listWorkspaces(),
    staleTime: 30_000,
  })
  const workspaces = workspacePack?.items ?? []

  const effectiveWorkspaceId = activeChatId ? (chat?.workspace_id ?? null) : storeWorkspaceId
  const name = useMemo(() => {
    if (!effectiveWorkspaceId) return null
    return workspaces.find((w) => w.id === effectiveWorkspaceId)?.name ?? null
  }, [effectiveWorkspaceId, workspaces])

  if (variant === 'inline') {
    return (
      <div className={cn('flex min-w-0 items-center', className)}>
        {name ? <span className="truncate text-sm font-medium text-foreground">{name}</span> : null}
      </div>
    )
  }

  if (!name) return null
  return (
    <div className="hidden shrink-0 justify-center border-b border-border py-2 md:flex">
      <span className="truncate text-sm font-medium text-foreground">{name}</span>
    </div>
  )
}
