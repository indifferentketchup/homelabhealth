import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import {
  changePassword,
  fetchMe,
  patchProfile,
  uploadProfileIcon,
} from '@/api/auth.js'
import { Button } from '@/components/ui/button'
import { PATH_808NOTES_HOME, PATH_BOOOPS_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'
import { fileToProfileAvatarDataUrl } from '@/lib/profileAvatarImage.js'

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
  const avatarDataUrl = useAppStore((s) => s.userProfile.avatarDataUrl)
  const setUserProfile = useAppStore((s) => s.setUserProfile)
  const setCurrentUser = useAppStore((s) => s.setCurrentUser)
  const syncUserProfileFromServer = useAppStore((s) => s.syncUserProfileFromServer)

  const isDbAccount = Boolean(currentUser?.user_id)
  const isEnvOwner = currentUser?.role === 'owner' && !currentUser?.user_id

  const [displayName, setDisplayName] = useState(userProfile.displayName)
  const [emoji, setEmoji] = useState(userProfile.emoji)
  const [bio, setBio] = useState(userProfile.bio)
  const [saved, setSaved] = useState(false)
  const [saveErr, setSaveErr] = useState(null)
  const [avatarErr, setAvatarErr] = useState(null)
  const [avatarBusy, setAvatarBusy] = useState(false)
  const avatarInputRef = useRef(null)

  const [curPassword, setCurPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [pwBusy, setPwBusy] = useState(false)
  const [pwMsg, setPwMsg] = useState(null)
  const [pwErr, setPwErr] = useState(null)

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
    if (!isDbAccount) return
    setDisplayName(userProfile.displayName)
    setEmoji(userProfile.emoji)
    setBio(userProfile.bio)
  }, [
    isDbAccount,
    currentUser?.user_id,
    userProfile.displayName,
    userProfile.emoji,
    userProfile.bio,
  ])

  const previewImg = isDbAccount ? profileIconObjectUrl || avatarDataUrl : avatarDataUrl

  async function onAvatarFile(e) {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (!f) return
    setAvatarErr(null)
    setAvatarBusy(true)
    try {
      if (isDbAccount) {
        await uploadProfileIcon(f)
        const me = await fetchMe()
        setCurrentUser(me)
        await syncUserProfileFromServer(me)
      } else {
        const dataUrl = await fileToProfileAvatarDataUrl(f)
        setUserProfile({ avatarDataUrl: dataUrl })
      }
    } catch (err) {
      setAvatarErr(err instanceof Error ? err.message : 'Could not use that image.')
    } finally {
      setAvatarBusy(false)
    }
  }

  async function clearAvatar() {
    setAvatarErr(null)
    if (isDbAccount) {
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
    } else {
      setUserProfile({ avatarDataUrl: '' })
    }
  }

  async function onSubmit(e) {
    e.preventDefault()
    setSaveErr(null)
    if (isDbAccount) {
      setAvatarBusy(false)
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
      return
    }
    setUserProfile({
      displayName: displayName.trim() || 'You',
      emoji: emoji.trim(),
      bio,
    })
    setSaved(true)
  }

  async function onPasswordSubmit(e) {
    e.preventDefault()
    setPwErr(null)
    setPwMsg(null)
    if (newPassword.length < 8) {
      setPwErr('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPwErr('New passwords do not match.')
      return
    }
    setPwBusy(true)
    try {
      await changePassword(curPassword, newPassword)
      setPwMsg('Password updated.')
      setCurPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setPwErr(err instanceof Error ? err.message : 'Could not change password.')
    } finally {
      setPwBusy(false)
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
        <p className="mb-6 text-sm text-muted-foreground">
          {isDbAccount
            ? 'Name, bio, photo, and password are saved to your account (shared between BooOps and 808notes when you use the same login).'
            : 'This is how you show up in BooOps and 808notes. As the site owner, display preferences here stay in this browser only; your sign-in password is set in server environment variables.'}
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

        {isDbAccount ? (
          <form onSubmit={(e) => void onPasswordSubmit(e)} className="mt-10 flex flex-col gap-4 border-t border-border pt-8">
            <h2 className="text-sm font-semibold text-foreground">Change password</h2>
            <div className="space-y-2">
              <label htmlFor="profile-cur-pw" className="text-sm font-medium text-foreground">
                Current password
              </label>
              <input
                id="profile-cur-pw"
                type="password"
                autoComplete="current-password"
                value={curPassword}
                onChange={(e) => setCurPassword(e.target.value)}
                className="fs-input w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                required
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="profile-new-pw" className="text-sm font-medium text-foreground">
                New password
              </label>
              <input
                id="profile-new-pw"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="fs-input w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                minLength={8}
                required
              />
              <p className="text-xs text-muted-foreground">At least 8 characters.</p>
            </div>
            <div className="space-y-2">
              <label htmlFor="profile-confirm-pw" className="text-sm font-medium text-foreground">
                Confirm new password
              </label>
              <input
                id="profile-confirm-pw"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="fs-input w-full rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                minLength={8}
                required
              />
            </div>
            {pwErr ? <p className="text-sm text-destructive">{pwErr}</p> : null}
            {pwMsg ? <p className="text-sm text-muted-foreground">{pwMsg}</p> : null}
            <Button type="submit" variant="secondary" disabled={pwBusy}>
              {pwBusy ? 'Updating…' : 'Update password'}
            </Button>
          </form>
        ) : null}

        {isEnvOwner ? (
          <p className="mt-8 text-xs text-muted-foreground">
            To change the owner password, update the server configuration (for example the password value used for the &quot;owner&quot; account), not this page.
          </p>
        ) : null}
      </div>
    </div>
  )
}
