import { useEffect, useState } from 'react'
import { Edit3, RefreshCw, Check, X } from 'lucide-react'
import { useRepoSyncStatus } from '@/hooks/useRepoSyncStatus.js'
import { cn } from '@/lib/utils.js'

function statusClass(status) {
  if (status === 'syncing') return 'bc-status-syncing'
  if (status === 'error')   return 'bc-status-error'
  return 'bc-status-idle'
}

function basename(p) {
  if (!p) return ''
  return p.replace(/\/+$/, '').split('/').pop() || p
}

export function RepoStatusBar({ dawId }) {
  const { data, liveProgress, triggerSync, updateConfig } = useRepoSyncStatus(dawId)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)

  useEffect(() => {
    const handler = () => setEditing(true)
    window.addEventListener('boocode:edit-repo-settings', handler)
    return () => window.removeEventListener('boocode:edit-repo-settings', handler)
  }, [])

  useEffect(() => {
    if (editing && data && !draft) {
      setDraft({
        repo_path: data.repo_path || '',
        repo_branch: data.repo_branch || 'main',
        repo_auto_sync: !!data.repo_auto_sync,
      })
    }
    if (!editing) setDraft(null)
  }, [editing, data, draft])

  if (!data) {
    return (
      <div className="bc-prompt-line">
        <span className="bc-prompt-dollar">$</span> boocode<span className="bc-caret" />
      </div>
    )
  }

  const status = data.status || 'idle'
  const branch = data.repo_branch || 'main'
  const path = data.repo_path || '(no repo)'
  const files = (liveProgress?.files_total ?? data.file_count) || 0
  const chunks = (liveProgress?.chunks_total ?? data.chunk_count) || 0
  const filesDone = liveProgress?.files_done

  const saveEdit = async () => {
    if (!draft) return
    setSaving(true); setErr(null)
    try {
      await updateConfig({
        repo_path: draft.repo_path || null,
        repo_branch: draft.repo_branch || 'main',
        repo_auto_sync: !!draft.repo_auto_sync,
      })
      setEditing(false)
    } catch (e) {
      setErr(e?.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bc-prompt-line relative">
      <span className="bc-prompt-dollar">$</span>
      <span className="bc-prompt-host">boocode</span>
      <span>@terminal:</span>
      {!editing ? (
        <>
          <span className="truncate">~{basename(path) ? `/${basename(path)}` : ''}</span>
          <span className="bc-prompt-branch">({branch})</span>
          <span className={cn('bc-status-pill', statusClass(status))}>
            {status}
            {status === 'syncing' && filesDone != null ? ` ${filesDone}/${files}` : null}
          </span>
          <span className="truncate text-xs" style={{ color: 'var(--text-muted)' }}>
            {files} files · {chunks} chunks
          </span>
          {data.error && status === 'error' && (
            <span className="truncate text-xs" style={{ color: '#ff6b6b' }}>{data.error}</span>
          )}
          <div className="ml-auto flex items-center gap-2">
            <button type="button"
                    disabled={status === 'syncing' || !data.repo_path}
                    onClick={triggerSync}
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs"
                    style={{ borderColor: 'var(--border)' }}>
              <RefreshCw className="size-3" />
              sync now
            </button>
            <button type="button" onClick={() => setEditing(true)}
                    className="inline-flex items-center rounded-md border p-1"
                    style={{ borderColor: 'var(--border)' }}
                    aria-label="Edit repo settings">
              <Edit3 className="size-3" />
            </button>
          </div>
        </>
      ) : (
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <input className="rounded border px-1 py-0.5 font-mono text-xs"
                 value={draft?.repo_path ?? ''}
                 onChange={(e) => setDraft((d) => ({ ...d, repo_path: e.target.value }))}
                 placeholder="/HomeLabRepos/…" />
          <span>(</span>
          <input className="w-24 rounded border px-1 py-0.5 font-mono text-xs"
                 value={draft?.repo_branch ?? ''}
                 onChange={(e) => setDraft((d) => ({ ...d, repo_branch: e.target.value }))}
                 placeholder="main" />
          <span>)</span>
          <label className="flex items-center gap-1 text-xs">
            <input type="checkbox" checked={!!draft?.repo_auto_sync}
                   onChange={(e) => setDraft((d) => ({ ...d, repo_auto_sync: e.target.checked }))} />
            auto-sync
          </label>
          {err && <span className="text-xs" style={{ color: '#ff6b6b' }}>{err}</span>}
          <div className="ml-auto flex items-center gap-1">
            <button type="button" onClick={saveEdit} disabled={saving}
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs"
                    style={{ borderColor: 'var(--orange)', color: 'var(--orange)' }}>
              <Check className="size-3" /> save
            </button>
            <button type="button" onClick={() => setEditing(false)}
                    className="inline-flex items-center rounded-md border p-1"
                    style={{ borderColor: 'var(--border)' }}
                    aria-label="Cancel edit">
              <X className="size-3" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
