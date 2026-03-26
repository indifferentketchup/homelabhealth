import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

/** Small circular avatar: uploaded image, else emoji, else first letter of display name. */
export function UserProfileAvatar({ className, size = 'button' }) {
  const avatarDataUrl = useAppStore((s) => s.userProfile.avatarDataUrl)
  const emoji = useAppStore((s) => s.userProfile.emoji)
  const displayName = useAppStore((s) => s.userProfile.displayName)
  const initial = (displayName && displayName.trim().slice(0, 1).toUpperCase()) || 'U'
  const glyph = emoji && emoji.trim() ? emoji.trim() : initial
  const dim =
    size === 'button'
      ? 'size-8 text-base'
      : size === 'lg'
        ? 'size-16 text-3xl'
        : 'size-10 text-xl'

  if (avatarDataUrl) {
    return (
      <img
        src={avatarDataUrl}
        alt=""
        className={cn('shrink-0 rounded-full border border-border object-cover', dim, className)}
      />
    )
  }

  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-full border border-border bg-muted font-medium text-muted-foreground',
        dim,
        className,
      )}
      aria-hidden
    >
      {glyph}
    </span>
  )
}
