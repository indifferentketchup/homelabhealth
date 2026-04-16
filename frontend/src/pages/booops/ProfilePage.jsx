import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import { fetchMe, patchProfile, uploadProfileIcon } from '@/api/auth.js'
import { Button } from '@/components/ui/button'
import { PATH_808NOTES_HOME, PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

function ProfilePreviewGlyph({ displayName, emoji }) {
  const initial = (displayName && displayName.trim().slice(0, 1).toUpperCase()) || 'U'
  const glyph = emoji && emoji.trim() ? emoji.trim() : initial
  return (
    <span
      className={cn(
        'inline-flex size-16 shrink-0 items-center justify-center rounded-full border border-border bg-muted font-medium text-muted-foreground',
        glyph.length > 1 ? 'text-3xl leading-none' : 'text-2xl',
      )}
      aria-hidden
    >
      {glyph}
    </span>
  )
}

export default function ProfilePage() {
  const mode = useAppStore((s) => s.mode)
  const homePath = mode === '808notes' ? PATH_808NOTES_HOME : PATH_BOOOPS_HOME
  const currentUser = useAppStore((s) => s.currentUser)
  const userProfile = useAppStore((s) => s.userProfile)
  const profileIconObjectUrl = useAppStore((s) => s.profileIconObjectUrl)
  const setCurrentUser = useAppStore((s) => s.setCurrentUser)
  const syncUserProfileFromServer = useAppStore((s) => s.syncUserProfileFromServer)

  const [displayName, setDisplayName] = useState(userProfile.displayName)
  const [emoji, setEmoji] = useState(userProfile.emoji)
  const [bio, setBio] = useState(userProfile.bio)
  const [saved, setSaved] = useState(false)
  const [saveErr, setSaveErr] = useState(null)
  const [avatarErr, setAvatarErr] = useState(null)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const avatarInputRef = useRef(null)

  useEffect(() => {
    if (!saved) return
    const t = window.setTimeout(() => setSaved(false), 2000)
    return () => window.clearTimeout(t)
  }, [saved])

  useEffect(() => {
    if (!avatarErr) return
    const t = window.setTimeout(() => setAvatarErr(null), 4000)
    return () => window.clearTimeout(t)
  }, [avatarErr])

  useEffect(() => {
    setDisplayName(userProfile.displayName)
    setEmoji(userProfile.emoji)
    setBio(userProfile.bio)
  }, [userProfile.displayName, userProfile.emoji, userProfile.bio])

  const previewImg = profileIconObjectUrl || ''

  async function onAvatarFile(e) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    setAvatarErr(null)
    setAvatarBusy(true)
    try {
      await uploadProfileIcon(f)
      const me = await fetchMe()
      setCurrentUser(me)
      await syncUserProfileFromServer(me)
    } catch (err) {
      setAvatarErr(err instanceof Error ? err.message : 'Could not use that image.')
    } finally {
      setAvatarBusy(false)
    }
  }

  async function clearAvatar() {
    setAvatarErr(null)
    setAvatarBusy(true)
    try {
      await patchProfile({ clear_icon: true })
      const me = await fetchMe()
      setCurrentUser(me)
      await syncUserProfileFromServer(me)
    } catch (err) {
      setAvatarErr(err instanceof Error ? err.message : 'Could not remove photo.')
    } finally {
      setAvatarBusy(false)
    }
  }

  async function onSubmit(e) {
    e.preventDefault()
    setSaveErr(null)
    try {
      await patchProfile({
        display_name: displayName.trim() || 'You',
        bio,
        avatar_emoji: emoji.trim(),
      })
      const me = await fetchMe()
      setCurrentUser(me)
      await syncUserProfileFromServer(me)
      setSaved(true)
    } catch (err) {
      setSaveErr(err instanceof Error ? err.message : 'Could not save profile.')
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Button type="button" variant="ghost" size="icon" asChild aria-label="Back">
          <Link to={homePath}>
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        <h1 className="text-sm font-semibold text-foreground">Your profile</h1>
      </div>
      <div className="mx-auto w-full max-w-lg p-4 md:p-8">
        {currentUser ? (
          <div className="mb-6 border-b border-border pb-4">
            <p className="text-base font-semibold text-foreground">{currentUser.display_name}</p>
            <p className="text-sm text-muted-foreground">@{currentUser.username}</p>
          </div>
        ) : null}
        <p className="mb-6 text-sm text-muted-foreground">
          Name, bio, and photo are saved to your account.
        </p>
        <form onSubmit={onSubmit} className="flex flex-col gap-6">
          <div className="flex flex-col items-center gap-3">
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => void onAvatarFile(e)}
            />
            {previewImg ? (
              <img
                src={previewImg}
                alt=""
                className="size-16 shrink-0 rounded-full border border-border object-cover"
              />
            ) : (
              <ProfilePreviewGlyph displayName={displayName} emoji={emoji} />
            )}
            <p className="text-center text-xs text-muted-foreground">
              Photo overrides emoji everywhere. Emoji or initial is used if you remove the photo.
            </p>
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={avatarBusy}
                onClick={() => avatarInputRef.current?.click()}
              >
                {avatarBusy ? 'Processing…' : 'Upload photo'}
              </Button>
              {previewImg ? (
                <Button type="button" size="sm" variant="outline" disabled={avatarBusy} onClick={() => void clearAvatar()}>
                  Remove photo
                </Button>
              ) : null}
            </div>
            {avatarErr ? <p className="text-center text-sm text-destructive">{avatarErr}</p> : null}
          </div>
          <div className="space-y-2">
            <label htmlFor="profile-name" className="text-sm font-medium text-foreground">
              Display name
            </label>
            <input
              id="profile-name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="fs-input w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="You"
              maxLength={80}
              autoComplete="nickname"
            />
          </div>
          <div className="space-y-2">
            <label htmlFor="profile-emoji" className="text-sm font-medium text-foreground">
              Emoji
            </label>
            <input
              id="profile-emoji"
              type="text"
              value={emoji}
              onChange={(e) => setEmoji(e.target.value)}
              className="fs-input w-full max-w-[8rem] rounded-md border border-border bg-background px-3 py-2 text-center text-2xl leading-none text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="👤"
              maxLength={8}
              inputMode="text"
            />
            <p className="text-xs text-muted-foreground">Clear the field to use the first letter of your name instead.</p>
          </div>
          <div className="space-y-2">
            <label htmlFor="profile-bio" className="text-sm font-medium text-foreground">
              Bio / notes
            </label>
            <textarea
              id="profile-bio"
              value={bio}
              onChange={(e) => setBio(e.target.value)}
              rows={4}
              className="fs-input w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder="Optional — reminders, preferences, etc."
              maxLength={2000}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit">Save</Button>
            {saved ? <span className="text-sm text-muted-foreground">Saved.</span> : null}
            {saveErr ? <span className="text-sm text-destructive">{saveErr}</span> : null}
          </div>
        </form>
      </div>
    </div>
  )
}
