import { useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Pin, PinOff, Plus, TerminalSquare, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useLongPress } from '@/hooks/useLongPress.js'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

function TabLabel({ session, isRenaming, onCommit, onCancel }) {
  const initial = session.label || session.machine_name || 'session'
  const [val, setVal] = useState(initial)
  const [wasRenaming, setWasRenaming] = useState(isRenaming)
  const inputRef = useRef(null)

  // Reset the draft each time an inline rename begins.
  if (isRenaming && !wasRenaming) {
    setWasRenaming(true)
    setVal(initial)
  } else if (!isRenaming && wasRenaming) {
    setWasRenaming(false)
  }

  useEffect(() => {
    if (!isRenaming) return
    const handle = window.setTimeout(() => {
      inputRef.current?.focus()
      inputRef.current?.select()
    }, 0)
    return () => window.clearTimeout(handle)
  }, [isRenaming])

  if (!isRenaming) {
    return (
      <span className="max-w-[18ch] truncate">
        {session.label || session.machine_name || 'session'}
      </span>
    )
  }

  return (
    <input
      ref={inputRef}
      value={val}
      onChange={(e) => setVal(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          onCommit(val.trim() || null)
        } else if (e.key === 'Escape') {
          e.preventDefault()
          onCancel()
        }
      }}
      onBlur={() => onCommit(val.trim() || null)}
      className="w-[14ch] bg-transparent px-1 text-inherit outline-none ring-1 ring-inset ring-[color:var(--orange,#ff8c00)]"
      style={{ fontFamily: "'JetBrains Mono', monospace" }}
    />
  )
}

function Tab({
  session,
  isActive,
  isRenaming,
  onActivate,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onPin,
  onClose,
  onSaveAndClose,
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const dot = session.device_count > 0

  function handleContextMenu(e) {
    e.preventDefault()
    if (!isActive) onActivate()
    setMenuOpen(true)
  }

  const lp = useLongPress(handleContextMenu)

  return (
    <DropdownMenu open={menuOpen} onOpenChange={setMenuOpen} modal={false}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          onClick={onActivate}
          onDoubleClick={onStartRename}
          onContextMenu={handleContextMenu}
          onTouchStart={lp.onTouchStart}
          onTouchMove={lp.onTouchMove}
          onTouchEnd={lp.onTouchEnd}
          onTouchCancel={lp.onTouchCancel}
          className="group/tab flex shrink-0 items-center gap-1.5 rounded border px-2 py-0.5 text-xs transition-colors"
          style={{
            borderColor: isActive ? 'var(--orange, #ff8c00)' : 'var(--border)',
            color: isActive ? 'var(--orange, #ff8c00)' : 'var(--text)',
            background: isActive ? 'var(--bg-card)' : 'transparent',
            fontFamily: "'JetBrains Mono', monospace",
            WebkitTouchCallout: 'none',
          }}
          aria-current={isActive ? 'true' : undefined}
        >
          {session.pinned ? (
            <Pin className="size-3 shrink-0" />
          ) : (
            <TerminalSquare className="size-3 shrink-0 opacity-70" />
          )}
          <TabLabel
            session={session}
            isRenaming={isRenaming}
            onCommit={onCommitRename}
            onCancel={onCancelRename}
          />
          {dot ? (
            <span
              className="inline-block size-1.5 shrink-0 rounded-full"
              style={{ background: '#3cff7a' }}
              aria-label="attached"
            />
          ) : null}
          {session.device_count > 1 ? (
            <span
              className="rounded px-1 text-[0.625rem] leading-4"
              style={{
                background: 'color-mix(in srgb, var(--orange, #ff8c00) 20%, transparent)',
                color: 'var(--orange, #ff8c00)',
              }}
            >
              {session.device_count}
            </span>
          ) : null}
          <span
            role="button"
            aria-label="Close tab"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              onClose()
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                e.stopPropagation()
                onClose()
              }
            }}
            className="ml-1 flex size-4 shrink-0 items-center justify-center rounded opacity-0 transition-opacity hover:bg-[color:var(--muted)] group-hover/tab:opacity-70 focus:opacity-100"
          >
            <X className="size-3" />
          </span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-44">
        <DropdownMenuItem onSelect={() => onStartRename()}>Rename</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onPin(!session.pinned)}>
          {session.pinned ? (
            <>
              <PinOff className="size-3.5" /> Unpin
            </>
          ) : (
            <>
              <Pin className="size-3.5" /> Pin
            </>
          )}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {onSaveAndClose && (
          <DropdownMenuItem onSelect={() => onSaveAndClose()}>
            Save &amp; Close
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => onClose()} className="text-destructive">
          <X className="size-3.5" /> Close
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default function TerminalTabBar({
  sessions,
  activeSessionId,
  onActivate,
  onNew,
  onRename,
  onPin,
  onClose,
  onSaveAndClose,
  trailing,
}) {
  const [renamingId, setRenamingId] = useState(null)

  const active = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || null,
    [sessions, activeSessionId],
  )
  const others = useMemo(
    () => sessions.filter((s) => s.id !== active?.id),
    [sessions, active?.id],
  )

  const commitRename = (id, label) => {
    setRenamingId(null)
    const current = sessions.find((s) => s.id === id)
    if (!current) return
    if ((current.label || null) === (label || null)) return
    onRename(id, label)
  }

  return (
    <div
      className="flex min-h-0 shrink-0 items-center gap-1 border-b px-2 py-1 text-xs"
      style={{
        borderColor: 'var(--border)',
        background: 'var(--bg-card)',
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      {/* Desktop: horizontally-scrolling strip showing every tab. */}
      <div
        className="hidden min-w-0 flex-1 items-center gap-1 overflow-x-auto sm:flex"
        style={{ scrollbarWidth: 'thin' }}
      >
        {sessions.map((s) => (
          <Tab
            key={s.id}
            session={s}
            isActive={s.id === activeSessionId}
            isRenaming={renamingId === s.id}
            onActivate={() => onActivate(s.id)}
            onStartRename={() => setRenamingId(s.id)}
            onCommitRename={(label) => commitRename(s.id, label)}
            onCancelRename={() => setRenamingId(null)}
            onPin={(next) => onPin(s.id, next)}
            onClose={() => onClose(s.id)}
            onSaveAndClose={onSaveAndClose ? () => onSaveAndClose(s.id) : undefined}
          />
        ))}
      </div>

      {/* Mobile: active tab + overflow dropdown. */}
      <div className="flex min-w-0 flex-1 items-center gap-1 sm:hidden">
        {active ? (
          <Tab
            session={active}
            isActive
            isRenaming={renamingId === active.id}
            onActivate={() => onActivate(active.id)}
            onStartRename={() => setRenamingId(active.id)}
            onCommitRename={(label) => commitRename(active.id, label)}
            onCancelRename={() => setRenamingId(null)}
            onPin={(next) => onPin(active.id, next)}
            onClose={() => onClose(active.id)}
            onSaveAndClose={onSaveAndClose ? () => onSaveAndClose(active.id) : undefined}
          />
        ) : null}
        {others.length > 0 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="xs" className="shrink-0 gap-1">
                + {others.length} more
                <ChevronDown className="size-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
              {others.map((s) => (
                <DropdownMenuItem
                  key={s.id}
                  onSelect={() => onActivate(s.id)}
                  className="flex items-center gap-2"
                >
                  {s.pinned ? <Pin className="size-3" /> : <TerminalSquare className="size-3 opacity-70" />}
                  <span className="flex-1 truncate">
                    {s.label || s.machine_name || 'session'}
                  </span>
                  {s.device_count > 0 ? (
                    <span
                      className="inline-block size-1.5 rounded-full"
                      style={{ background: '#3cff7a' }}
                    />
                  ) : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>

      <Button
        variant="ghost"
        size="icon-xs"
        aria-label="New terminal"
        onClick={onNew}
        className="shrink-0"
      >
        <Plus className="size-3.5" />
      </Button>
      {trailing}
    </div>
  )
}
