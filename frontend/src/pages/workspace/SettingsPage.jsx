import { useCallback, useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { deleteNonWorkspaceChats } from '@/api/chats.js'
import { getContextBarSetting, putContextBarSetting } from '@/api/settings.js'
import RefusalReviewTab from '@/components/settings/RefusalReviewTab.jsx'
import SearchSettingsTab from '@/components/settings/SearchSettingsTab.jsx'
import SystemTab from '@/components/settings/SystemTab.jsx'
import { Button } from '@/components/ui/button'
import { clearWorkspaceLayoutLiveDraft, setWorkspaceLayoutLiveDraft } from '@/lib/workspaceLayout.js'
import { cn } from '@/lib/utils'
import { PATH_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

const TABS = [
  { id: 'typography', label: 'Typography' },
  { id: 'layout', label: 'Layout' },
  { id: 'system', label: 'System' },
  { id: 'search', label: 'Search' },
  { id: 'safety', label: 'Safety Log' },
]

function clampTypographyFs(n, lo = 10, hi = 32) {
  const v = typeof n === 'number' ? n : Number(n)
  if (!Number.isFinite(v)) return lo
  return Math.min(hi, Math.max(lo, Math.round(v)))
}

function FontSizeRow({ label, value, onChange }) {
  const n = clampTypographyFs(value)
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-44 shrink-0 text-muted-foreground">{label}</span>
      <div className="flex flex-1 items-center justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={() => onChange(n - 1)}
          disabled={n <= 10}
          aria-label={`Decrease ${label}`}
        >
          −
        </Button>
        <span className="min-w-[3rem] text-center tabular-nums text-foreground">{n}px</span>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="h-9 w-9 shrink-0"
          onClick={() => onChange(n + 1)}
          disabled={n >= 24}
          aria-label={`Increase ${label}`}
        >
          +
        </Button>
      </div>
    </div>
  )
}

function layoutDraftToApiPayload(draft) {
  const out = { ...draft }
  if (out.fontSize != null) out.fontSize = clampTypographyFs(out.fontSize)
  for (const k of ['fsNav', 'fsChat', 'fsInput', 'fsHeading', 'fsCode']) {
    if (out[k] != null) out[k] = clampTypographyFs(out[k])
  }
  if (out.sidebarWidth != null) out.sidebarWidth = Math.round(Number(out.sidebarWidth)) || 260
  if (out.chatMaxWidth != null) out.chatMaxWidth = Math.round(Number(out.chatMaxWidth)) || 1200
  return out
}

function ContextBarToggle() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['settings', 'context-bar'],
    queryFn: getContextBarSetting,
    staleTime: 30_000,
  })
  const enabled = data?.show_context_bar ?? false
  const [saving, setSaving] = useState(false)

  async function toggle() {
    setSaving(true)
    try {
      const result = await putContextBarSetting(!enabled)
      queryClient.setQueryData(['settings', 'context-bar'], result)
    } catch {
      /* ignore */
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-10 space-y-3 border-t border-border pt-6">
      <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Display</h2>
      <label className="flex items-start gap-3 cursor-pointer">
        <input
          type="checkbox"
          checked={enabled}
          onChange={() => void toggle()}
          disabled={isLoading || saving}
          className="mt-0.5 size-4 shrink-0 accent-primary"
        />
        <div className="space-y-1">
          <span className="text-sm font-medium text-foreground">Context usage indicator</span>
          <p className="text-xs text-muted-foreground">
            Shows how much of the model&apos;s context window is used by the current conversation.
            Helps you know when chats are getting long. The system automatically summarizes older
            messages when usage reaches ~85%.
          </p>
        </div>
      </label>
    </div>
  )
}

export default function SettingsPage({ onClose }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const settingsTabs = useMemo(() => TABS, [])
  const [tab, setTabState] = useState(() => {
    try {
      if (typeof window !== 'undefined') {
        const fromUrl = new URLSearchParams(window.location.search).get('tab')
        if (fromUrl && settingsTabs.some((t) => t.id === fromUrl)) return fromUrl
      }
      const v = localStorage.getItem('homelabhealth-settings-tab')
      if (v && settingsTabs.some((t) => t.id === v)) return v
    } catch {
      /* ignore */
    }
    return 'typography'
  })

  const setTab = useCallback((id) => {
    setTabState(id)
    try {
      localStorage.setItem('homelabhealth-settings-tab', id)
    } catch {
      /* ignore */
    }
  }, [])

  const handleClose = useCallback(() => {
    if (onClose) onClose()
    else navigate(PATH_HOME)
  }, [onClose, navigate])

  useEffect(() => {
    if (!onClose) return
    const onKey = (e) => {
      if (e.key === 'Escape') handleClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose, handleClose])

  const [globalDraft, setGlobalDraft] = useState(() => layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
  const [typographySaving, setTypographySaving] = useState(false)
  const [layoutSaving, setLayoutSaving] = useState(false)

  useEffect(() => {
    // Subscribe to the store so that when WorkspaceApp's loadLayout completes,
    // globalDraft gets the API-fresh values  -  without firing a redundant second
    // GET /api/settings/layout request (double loadLayout dedup).
    const unsub = useLayoutStore.subscribe(() => {
      setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
      unsub()
    })
    return unsub
  }, [])

  const applyLiveGlobal = useCallback((draft) => {
    setWorkspaceLayoutLiveDraft({
      sidebarWidth: draft.sidebarWidth,
      chatMaxWidth: draft.chatMaxWidth,
    })
  }, [])

  const updateGlobalDraft = useCallback(
    (patch) => {
      setGlobalDraft((prev) => {
        const next = { ...prev, ...patch }
        applyLiveGlobal(next)
        return next
      })
    },
    [applyLiveGlobal],
  )

  async function saveGlobalToApi(partial) {
    await useLayoutStore.getState().saveLayout(partial)
    try {
      localStorage.removeItem('workspace_layout')
    } catch {
      /* ignore */
    }
    clearWorkspaceLayoutLiveDraft()
  }

  async function saveTypography() {
    setTypographySaving(true)
    try {
      const base = clampTypographyFs(globalDraft.fontSize)
      await saveGlobalToApi({
        fontSize: base,
        fsNav: clampTypographyFs(globalDraft.fsNav),
        fsChat: clampTypographyFs(globalDraft.fsChat),
        fsInput: clampTypographyFs(globalDraft.fsInput),
        fsHeading: clampTypographyFs(globalDraft.fsHeading),
        fsCode: clampTypographyFs(globalDraft.fsCode),
      })
      setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
      toast.success('Typography saved')
    } finally {
      setTypographySaving(false)
    }
  }

  async function saveLayoutPrefs() {
    setLayoutSaving(true)
    try {
      await saveGlobalToApi({
        sidebarWidth: Number(globalDraft.sidebarWidth) || 260,
        chatMaxWidth: Number(globalDraft.chatMaxWidth) || 1200,
      })
      setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
      toast.success('Layout saved')
    } finally {
      setLayoutSaving(false)
    }
  }

  const fontSizeBase = clampTypographyFs(globalDraft.fontSize ?? 15)
  const sidebarWidth = Number(globalDraft.sidebarWidth) || 260
  const chatMaxWidth = Number(globalDraft.chatMaxWidth) || 1200

  const setActiveChatId = useAppStore((s) => s.setActiveChatId)
  const [purgeConfirm, setPurgeConfirm] = useState(false)
  const [purgeBusy, setPurgeBusy] = useState(false)
  const [purgeMsg, setPurgeMsg] = useState(null)

  async function onDeleteNonWorkspaceChatsClick() {
    setPurgeBusy(true)
    setPurgeMsg(null)
    try {
      const res = await deleteNonWorkspaceChats()
      const n = typeof res?.deleted === 'number' ? res.deleted : 0
      setPurgeMsg(`Deleted ${n} chat${n === 1 ? '' : 's'} without a workspace.`)
      setPurgeConfirm(false)
      setActiveChatId(null)
      await queryClient.invalidateQueries({ queryKey: ['chats'] })
    } catch (e) {
      setPurgeMsg(e instanceof Error ? e.message : 'Delete failed')
    } finally {
      setPurgeBusy(false)
    }
  }

  useEffect(() => {
    if (!purgeMsg) return
    const t = window.setTimeout(() => setPurgeMsg(null), 5000)
    return () => window.clearTimeout(t)
  }, [purgeMsg])

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-background">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-4">
        <h1 id="settings-title" className="fs-heading font-semibold tracking-tight text-foreground">
          Settings
        </h1>
        {onClose ? (
          <Button type="button" variant="ghost" size="icon" className="shrink-0" aria-label="Close settings" onClick={handleClose}>
            <X className="size-5" />
          </Button>
        ) : null}
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 overflow-x-auto border-b border-border" role="tablist" aria-label="Settings sections">
          <div className="flex flex-row">
            {settingsTabs.map((t) => (
              <button
                key={t.id}
                id={`tab-${t.id}`}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                aria-controls={`panel-${t.id}`}
                onClick={() => setTab(t.id)}
                className={cn(
                  'shrink-0 px-4 py-3 text-sm whitespace-nowrap transition-colors',
                  tab === t.id
                    ? 'border-b-2 border-primary font-medium text-foreground'
                    : 'border-b-2 border-transparent text-muted-foreground hover:text-foreground',
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        <div
          id={`panel-${tab}`}
          role="tabpanel"
          aria-labelledby={`tab-${tab}`}
          className="min-h-0 flex-1 overflow-y-auto px-4 py-6"
        >
          {tab === 'typography' && (
            <section className="mx-auto w-full max-w-2xl space-y-6">
              <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Typography (global)</h2>
              <p className="text-sm text-muted-foreground">Applies to the workspace.</p>

              <div className="space-y-3">
                <h3 className="text-sm font-medium text-foreground">Font sizes</h3>
                <FontSizeRow
                  label="Base"
                  value={fontSizeBase}
                  onChange={(n) => updateGlobalDraft({ fontSize: n })}
                />
                <FontSizeRow label="Nav / sidebar" value={globalDraft.fsNav} onChange={(n) => updateGlobalDraft({ fsNav: n })} />
                <FontSizeRow label="Chat messages" value={globalDraft.fsChat} onChange={(n) => updateGlobalDraft({ fsChat: n })} />
                <FontSizeRow label="Chat input" value={globalDraft.fsInput} onChange={(n) => updateGlobalDraft({ fsInput: n })} />
                <FontSizeRow label="Headings" value={globalDraft.fsHeading} onChange={(n) => updateGlobalDraft({ fsHeading: n })} />
                <FontSizeRow label="Code blocks" value={globalDraft.fsCode} onChange={(n) => updateGlobalDraft({ fsCode: n })} />
              </div>

              <Button type="button" size="sm" onClick={() => void saveTypography()} disabled={typographySaving}>
                {typographySaving ? 'Saving…' : 'Save typography'}
              </Button>
            </section>
          )}

          {tab === 'layout' && (
            <section className="mx-auto w-full max-w-2xl space-y-3">
              <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Layout (global)</h2>
              <p className="text-sm text-muted-foreground">Sidebar and chat width apply globally. The sources column matches sidebar width.</p>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Sidebar width ({sidebarWidth}px)</span>
                <input
                  type="range"
                  min={200}
                  max={400}
                  step={1}
                  value={sidebarWidth}
                  onChange={(e) => updateGlobalDraft({ sidebarWidth: parseInt(e.target.value, 10) })}
                  className="w-full"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Chat max width ({chatMaxWidth}px)</span>
                <input
                  type="range"
                  min={480}
                  max={1500}
                  step={10}
                  value={chatMaxWidth}
                  onChange={(e) => updateGlobalDraft({ chatMaxWidth: parseInt(e.target.value, 10) })}
                  className="w-full"
                />
              </label>
              <Button type="button" size="sm" onClick={() => void saveLayoutPrefs()} disabled={layoutSaving}>
                {layoutSaving ? 'Saving…' : 'Save layout'}
              </Button>

              <ContextBarToggle />

              <div className="mt-10 space-y-3 border-t border-border pt-6">
                <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Chats</h2>
                <p className="text-sm text-muted-foreground">
                  Delete every chat that is{' '}
                  <span className="font-medium text-foreground">not</span> linked to a workspace. This cannot be undone.
                </p>
                {purgeMsg ? <p className="text-sm text-foreground">{purgeMsg}</p> : null}
                {!purgeConfirm ? (
                  <Button type="button" size="sm" variant="destructive" onClick={() => setPurgeConfirm(true)}>
                    Delete all non-workspace chats
                  </Button>
                ) : (
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-destructive">Are you sure?</span>
                    <Button
                      type="button"
                      size="sm"
                      variant="destructive"
                      disabled={purgeBusy}
                      onClick={() => void onDeleteNonWorkspaceChatsClick()}
                    >
                      {purgeBusy ? 'Deleting…' : 'Yes, delete'}
                    </Button>
                    <Button type="button" size="sm" variant="outline" disabled={purgeBusy} onClick={() => setPurgeConfirm(false)}>
                      Cancel
                    </Button>
                  </div>
                )}
              </div>
            </section>
          )}

          {tab === 'system' && <SystemTab />}

          {tab === 'search' && <SearchSettingsTab />}

          {tab === 'safety' && <RefusalReviewTab />}
        </div>
      </div>
    </div>
  )
}
