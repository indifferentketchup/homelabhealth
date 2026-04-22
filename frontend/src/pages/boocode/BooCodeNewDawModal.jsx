import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { createDaw, deleteDaw } from '@/api/daws.js'
import { updateRepoConfig, syncRepo } from '@/api/boocode.js'

const URL_RE = /^https?:\/\/(github\.com|gitlab\.com|bitbucket\.org)\/[^/]+\/([^/?#]+?)(?:\.git)?\/?$/i

function suggestPathFromUrl(input) {
  const m = (input || '').trim().match(URL_RE)
  if (!m) return null
  const repo = m[2].replace(/\.git$/i, '')
  return `/HomeLabRepos/${repo}`
}

export default function BooCodeNewDawModal({ onClose, onStart, onCreated }) {
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [repoPath, setRepoPath] = useState('')
  const [branch, setBranch] = useState('main')
  const [autoSync, setAutoSync] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState(null)
  const suggestion = suggestPathFromUrl(repoPath)

  const submit = async () => {
    setErr(null)
    if (!name.trim()) { setErr('Name is required.'); return }
    const path = repoPath.trim()
    if (!path) { setErr('Repo path is required.'); return }
    if (!path.startsWith('/HomeLabRepos/')) {
      setErr('Repo path must start with /HomeLabRepos/.')
      return
    }
    setSubmitting(true)
    onStart?.({ name: name.trim() })
    let created = null
    try {
      created = await createDaw({
        mode: 'boocode',
        name: name.trim(),
        color: '#ff8c00',
      })
      try {
        await updateRepoConfig(created.id, {
          repo_path: path,
          repo_branch: branch.trim() || 'main',
          repo_auto_sync: autoSync,
        })
      } catch (e) {
        try { await deleteDaw(created.id) } catch { /* ignore rollback failure */ }
        throw e
      }
      if (autoSync) {
        try { await syncRepo(created.id) } catch { /* 409/400 acceptable */ }
      }
      await qc.invalidateQueries({ queryKey: ['daws', 'boocode'] })
      onCreated?.(created)
    } catch (e) {
      onStart?.(null)
      setErr(e?.message || 'Could not create DAW.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose?.() }}>
      <DialogContent
        className="sm:max-w-lg"
        style={{
          background: 'var(--bg-panel)',
          borderColor: 'color-mix(in srgb, var(--orange) 40%, transparent)',
          boxShadow: 'var(--glow-orange)',
        }}
      >
        <DialogHeader>
          <DialogTitle
            style={{
              fontFamily: "'Orbitron', sans-serif",
              letterSpacing: '0.2em',
              color: 'var(--orange)',
            }}
          >
            NEW BOOCODE DAW
          </DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2"
             style={{ fontFamily: "'JetBrains Mono', monospace" }}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bc-new-name">Name</Label>
            <Input id="bc-new-name" value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="e.g. boolab-api" autoFocus />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bc-new-path">Repo path</Label>
            <Input id="bc-new-path" value={repoPath} onChange={(e) => setRepoPath(e.target.value)}
                   placeholder="/HomeLabRepos/…" />
            {suggestion && suggestion !== repoPath.trim() && (
              <button type="button"
                      className="self-start text-xs underline"
                      style={{ color: 'var(--orange)' }}
                      onClick={() => setRepoPath(suggestion)}>
                use {suggestion}
              </button>
            )}
            <div className="text-[0.6875rem]" style={{ color: 'var(--text-dim)' }}>
              Path must start with /HomeLabRepos/.
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="bc-new-branch">Branch</Label>
            <Input id="bc-new-branch" value={branch} onChange={(e) => setBranch(e.target.value)} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={autoSync} onChange={(e) => setAutoSync(e.target.checked)} />
            <span>Sync immediately on create + auto-sync on changes</span>
          </label>
          {err && (
            <div className="rounded-md border px-3 py-2 text-xs"
                 style={{ borderColor: '#ff6b6b', color: '#ff6b6b', background: 'transparent' }}>
              {err}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={submitting}>Cancel</Button>
          <Button onClick={submit} disabled={submitting}
                  style={{
                    borderColor: 'var(--orange)',
                    color: 'var(--orange)',
                    background: 'var(--bg-card)',
                    fontFamily: "'Orbitron', sans-serif",
                    letterSpacing: '0.2em',
                  }}>
            {submitting ? 'CREATING…' : 'CREATE'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
