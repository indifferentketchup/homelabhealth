import { useEffect } from 'react'
import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils.js'
import { RepoFilesPanel } from '@/pages/boocode/RepoFilesPanel.jsx'
import { RepoStatusBar } from '@/pages/boocode/RepoStatusBar.jsx'

/**
 * MobileRightDrawer — slide-in right-side sheet for the repo files browser.
 *
 * Mirrors the left sidebar mobile drawer pattern (Sidebar.jsx lines 578-591).
 * Only visible on mobile (<md) — desktop shows the pinned `aside` in
 * BooCodeDawWorkspace instead.
 *
 * Props:
 *   open    — boolean, whether the drawer is visible
 *   onClose — () => void, called when backdrop or Escape is pressed
 *   dawId   — string | null, current DAW; gates RepoFilesPanel render
 */
export function MobileRightDrawer({ open, onClose, dawId }) {
  // Keyboard: Escape closes the drawer.
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  return (
    <>
      {/* Backdrop — same z-30 + opacity pattern as left sidebar backdrop */}
      {open && (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-background/70 md:hidden"
          aria-label="Close repo files"
          onClick={onClose}
        />
      )}

      {/* Drawer panel — z-40 so it sits above the backdrop */}
      <aside
        className={cn(
          'fixed inset-y-0 right-0 z-40 flex w-72 max-w-[85vw] flex-col',
          'bg-sidebar text-sidebar-foreground',
          'border-l border-sidebar-border',
          'transition-transform duration-200 ease-out md:hidden',
          open ? 'translate-x-0 shadow-[var(--glow)]' : 'translate-x-full',
        )}
        role="complementary"
        aria-label="Repo files"
        aria-hidden={!open}
      >
        {/* Header row */}
        <div className="flex shrink-0 items-center justify-between border-b border-sidebar-border px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
            Repo Files
          </span>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label="Close repo files"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>

        {/* Body — RepoStatusBar at top, RepoFilesPanel fills remaining */}
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {dawId ? (
            <>
              <div className="shrink-0 border-b border-sidebar-border">
                <RepoStatusBar dawId={dawId} />
              </div>
              <div className="min-h-0 flex-1 overflow-hidden">
                <RepoFilesPanel dawId={dawId} />
              </div>
            </>
          ) : (
            <p className="p-4 text-sm text-muted-foreground">
              Open a DAW to see its files.
            </p>
          )}
        </div>
      </aside>
    </>
  )
}
