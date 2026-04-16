import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { UserProfileAvatar } from '@/components/layout/UserProfileAvatar.jsx'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

function useFixedRect(anchorRef, open) {
  const [rect, setRect] = useState(null)
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return
    setRect(anchorRef.current.getBoundingClientRect())
  }, [open, anchorRef])
  return rect
}

function ProfileDropdownPanel({ rect, children }) {
  if (!rect) return null
  const minW = Math.max(rect.width, 11 * 16)
  const pad = 8
  const right = typeof window !== 'undefined' ? window.innerWidth - rect.right : 0
  return (
    <div
      className="flex min-w-0 flex-col gap-0 p-1"
      style={{
        zIndex: 9999,
        position: 'fixed',
        top: `${rect.bottom + 4}px`,
        right: `${Math.max(pad, right)}px`,
        left: 'auto',
        width: `${minW}px`,
        maxWidth: `calc(100vw - ${2 * pad}px)`,
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
      role="menu"
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>
  )
}

/**
 * Top profile control. Single-user: always a menu with Account Settings.
 * @param {object} props
 * @param {string} props.profilePath
 * @param {'header' | 'fixed'} props.placement
 * @param {() => void} [props.onAfterNavigate]
 */
export function UserProfileMenu({ profilePath, placement, onAfterNavigate }) {
  const navigate = useNavigate()
  const currentUser = useAppStore((s) => s.currentUser)

  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const anchorRef = useRef(null)
  const rect = useFixedRect(anchorRef, open)

  useEffect(() => {
    if (!open) return
    function onMouseDown(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open])

  const finishNavigate = () => {
    onAfterNavigate?.()
    setOpen(false)
  }

  const onAccountSettings = () => {
    navigate(profilePath)
    finishNavigate()
  }

  const headerAvatar = <UserProfileAvatar size="button" className="size-7 text-sm" />
  const fixedAvatar = <UserProfileAvatar size="button" />

  if (!currentUser) {
    if (placement === 'header') {
      return (
        <Button type="button" variant="ghost" size="icon" className="shrink-0" asChild aria-label="Your profile">
          <Link to={profilePath} onClick={onAfterNavigate}>
            {headerAvatar}
          </Link>
        </Button>
      )
    }
    return (
      <Link
        to={profilePath}
        className="pointer-events-auto fixed right-3 top-3 z-40 hidden rounded-full border border-border bg-card shadow-sm md:inline-flex"
        aria-label="Your profile"
        onClick={onAfterNavigate}
      >
        <span className="p-0.5">{fixedAvatar}</span>
      </Link>
    )
  }

  if (placement === 'header') {
    return (
      <div ref={wrapRef} className="shrink-0">
        <span ref={anchorRef} className="inline-flex">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0"
            aria-label="Account menu"
            aria-expanded={open}
            aria-haspopup="menu"
            onClick={() => setOpen((o) => !o)}
          >
            {headerAvatar}
          </Button>
        </span>
        {open && (
          <ProfileDropdownPanel rect={rect}>
            <button
              type="button"
              role="menuitem"
              className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-2 text-left text-sm outline-none hover:bg-accent hover:text-accent-foreground"
              onClick={onAccountSettings}
            >
              Account Settings
            </button>
          </ProfileDropdownPanel>
        )}
      </div>
    )
  }

  return (
    <div
      ref={wrapRef}
      className={cn(
        'pointer-events-auto fixed right-3 top-3 z-40 hidden rounded-full border border-border bg-card shadow-sm md:inline-flex',
      )}
    >
      <span ref={anchorRef} className="inline-flex">
        <button
          type="button"
          className="rounded-full p-0.5 outline-none ring-ring focus-visible:ring-2"
          aria-label="Account menu"
          aria-expanded={open}
          aria-haspopup="menu"
          onClick={() => setOpen((o) => !o)}
        >
          {fixedAvatar}
        </button>
      </span>
      {open && (
        <ProfileDropdownPanel rect={rect}>
          <button
            type="button"
            role="menuitem"
            className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-2 text-left text-sm outline-none hover:bg-accent hover:text-accent-foreground"
            onClick={onAccountSettings}
          >
            Account Settings
          </button>
          <button
            type="button"
            role="menuitem"
            className="fs-nav flex w-full cursor-default items-center rounded-sm px-2 py-2 text-left text-sm text-destructive outline-none hover:bg-destructive/10"
            onClick={onLogOut}
          >
            Log Out
          </button>
        </ProfileDropdownPanel>
      )}
    </div>
  )
}
