import { useQuery } from '@tanstack/react-query'
import { Terminal } from 'lucide-react'

import * as terminalsApi from '@/api/terminals.js'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useAppStore } from '@/store/index.js'

/**
 * Right-click "Send to Terminal" context menu for chat code blocks.
 *
 * Controlled via `open` / `onOpenChange`. The `anchor` prop supplies the
 * viewport-relative click position; an invisible 1px trigger is fixed at
 * that point so Radix positions the portal content near the cursor.
 *
 * @param {{ open: boolean, onOpenChange: (v: boolean) => void, anchor: {x: number, y: number} | null, text: string }} props
 */
export function SendToTerminalMenu({ open, onOpenChange, anchor, text }) {
  const activeDawId = useAppStore((s) => s.activeDawId)

  const { data } = useQuery({
    queryKey: ['send-to-terminal-menu', activeDawId],
    queryFn: () => terminalsApi.list({ dawId: activeDawId }),
    enabled: open && Boolean(activeDawId),
    staleTime: 5000,
  })

  // Sort: pinned first, then by created_at ascending (same pattern as Sidebar)
  const sessions = (data?.active ?? []).slice().sort((a, b) => {
    if (a.pinned && !b.pinned) return -1
    if (!a.pinned && b.pinned) return 1
    return (a.created_at ?? '') < (b.created_at ?? '') ? -1 : 1
  })

  function handleSelect(sessionId) {
    window.dispatchEvent(
      new CustomEvent('boocode:send-to-terminal', {
        detail: { sessionId, text, appendNewline: true },
      }),
    )
    onOpenChange(false)
  }

  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      {/*
       * Invisible 1×1px trigger fixed at the click position.
       * Radix measures the trigger's bounding rect to anchor the portal,
       * so placing it at the cursor makes the menu appear near the right-click point.
       * `asChild` with a plain span prevents Radix from rendering an extra button.
       */}
      <DropdownMenuTrigger asChild>
        <span
          aria-hidden
          tabIndex={-1}
          style={{
            position: 'fixed',
            top: anchor ? anchor.y : 0,
            left: anchor ? anchor.x : 0,
            width: 1,
            height: 1,
            pointerEvents: 'none',
            opacity: 0,
          }}
        />
      </DropdownMenuTrigger>

      <DropdownMenuContent
        align="start"
        sideOffset={2}
        onCloseAutoFocus={(e) => e.preventDefault()}
      >
        <DropdownMenuLabel className="flex items-center gap-1.5">
          <Terminal className="size-3.5 shrink-0" />
          Send to Terminal
        </DropdownMenuLabel>
        <DropdownMenuSeparator />

        {!activeDawId ? (
          <DropdownMenuItem disabled>
            No DAW — open one first
          </DropdownMenuItem>
        ) : sessions.length === 0 ? (
          <>
            <DropdownMenuItem disabled>No active terminals</DropdownMenuItem>
            <DropdownMenuItem disabled className="text-xs text-muted-foreground">
              {'ℹ'} {'⌘'}K → new terminal
            </DropdownMenuItem>
          </>
        ) : (
          sessions.map((s) => (
            <DropdownMenuItem
              key={s.id}
              onSelect={() => handleSelect(s.id)}
              className="flex items-center gap-2"
            >
              <Terminal className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate">
                {s.label || s.machine_name || 'session'}
              </span>
              {s.device_count > 0 && (
                <span
                  className="size-2 shrink-0 rounded-full bg-green-500"
                  aria-label="active"
                />
              )}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
