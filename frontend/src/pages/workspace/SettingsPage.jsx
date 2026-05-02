import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import * as LucideIcons from 'lucide-react'
import { X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { apiFetch } from '@/api/index.js'
import { deleteNonWorkspaceChats } from '@/api/chats.js'
import {
  DEFAULT_BRANDING,
  FONT_BODY_OPTIONS,
  FONT_BODY_STACKS,
  FONT_MONO_OPTIONS,
  applyBrandingCss,
  deleteBrandingAsset,
  fetchBranding,
  layoutApiToBrandingPatchSansTheme,
  mergeBrandingWithGlobalLayout,
  patchBranding,
  patchBrandingApi,
  uploadBrandingAsset,
} from '@/api/branding.js'
import SearchSettingsTab from '@/components/settings/SearchSettingsTab.jsx'
import { SkillsLibraryPage } from '@/pages/SkillsLibraryPage.jsx'
import { Button } from '@/components/ui/button'
import { clearWorkspaceLayoutLiveDraft, setWorkspaceLayoutLiveDraft } from '@/lib/workspaceLayout.js'
import { cn } from '@/lib/utils'
import { PATH_HOME } from '@/routes/paths.js'
import { useAppStore } from '@/store/index.js'
import { useLayoutStore } from '@/store/layoutStore.js'

const COLOR_KEYS = [
  ['accentColor', 'Accent'],
  ['accentCyan', 'Accent cyan'],
  ['accentPurple', 'Accent purple'],
  ['bgColor', 'Background'],
  ['bgPanel', 'Panel'],
  ['bgCard', 'Card'],
  ['textColor', 'Text'],
  ['textDim', 'Text dim'],
  ['borderColor', 'Border'],
]

const TABS = [
  { id: 'branding', label: 'Branding' },
  { id: 'colors', label: 'Colors' },
  { id: 'typography', label: 'Typography' },
  { id: 'layout', label: 'Layout' },
  { id: 'search', label: 'Search' },
  { id: 'skills', label: 'Skills' },
]

/** Lucide export names — right-click branding cards to pick. Invalid names fall back. */
const GLYPH_PICKER_ICONS = [
  'Bot',
  'Music2',
  'Sparkles',
  'MessageSquare',
  'Headphones',
  'Mic2',
  'Cpu',
  'Heart',
  'Star',
  'Zap',
  'Wand2',
  'LayoutGrid',
  'Library',
  'Radio',
]

function lucideGlyphComponent(name, fallback) {
  const pick = (n) => {
    const C = LucideIcons[n]
    return C && typeof C === 'function' ? C : null
  }
  return pick(name) || pick(fallback) || LucideIcons.Circle
}

function clampTypographyFs(n, lo = 10, hi = 24) {
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

const selectClass =
  'h-9 w-full rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2'

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

export default function SettingsPage({ onClose }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const settingsTabs = useMemo(() => TABS, [])
  const [brandingSaveError, setBrandingSaveError] = useState(null)
  const [glyphMenu, setGlyphMenu] = useState(null)
  const glyphMenuRef = useRef(null)
  const [tab, setTabState] = useState(() => {
    try {
      const v = localStorage.getItem('homelabhealth-settings-tab')
      if (v && settingsTabs.some((t) => t.id === v)) return v
    } catch {
      /* ignore */
    }
    return 'branding'
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

  useEffect(() => {
    void useLayoutStore
      .getState()
      .loadLayout()
      .then(() => {
        setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
      })
  }, [])

  const applyLiveGlobal = useCallback(
    (draft) => {
      const row =
        useAppStore.getState().branding ?? queryClient.getQueryData(['branding'])
      if (!row || typeof row !== 'object') return
      const patch = layoutApiToBrandingPatchSansTheme(draft)
      const merged = patchBranding(row, patch)
      applyBrandingCss(merged)
      setWorkspaceLayoutLiveDraft({
        sidebarWidth: draft.sidebarWidth,
        chatMaxWidth: draft.chatMaxWidth,
      })
    },
    [queryClient],
  )

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

  const { data: brandingConfigRow } = useQuery({
    queryKey: ['branding', 'config'],
    queryFn: () => apiFetch('/api/branding/'),
    staleTime: 60_000,
  })

  const brandingDefaults = useMemo(() => DEFAULT_BRANDING, [])

  const [localBranding, setLocalBranding] = useState(() => ({ ...DEFAULT_BRANDING }))
  useEffect(() => {
    setLocalBranding({ ...DEFAULT_BRANDING })
  }, [])

  useEffect(() => {
    if (brandingConfigRow && typeof brandingConfigRow === 'object') {
      setLocalBranding(patchBranding(null, brandingConfigRow))
    }
  }, [brandingConfigRow])

  const pushBrandingPreview = useCallback(
    (next) => {
      const merged = patchBranding(null, next)
      const layoutPayload = layoutDraftToApiPayload({ ...useLayoutStore.getState() })
      const withLayout = mergeBrandingWithGlobalLayout(merged, layoutPayload, { stripTheme: true })
      const finalized = patchBranding(null, withLayout)
      applyBrandingCss(finalized)
      queryClient.setQueryData(['branding'], finalized)
    },
    [queryClient],
  )

  const updateBrandingField = useCallback(
    (patch) => {
      setLocalBranding((prev) => {
        const next = { ...prev, ...patch }
        pushBrandingPreview(next)
        return next
      })
    },
    [pushBrandingPreview],
  )

  const persistAppGlyphIcon = useCallback(
    async (lucideName) => {
      setGlyphMenu(null)
      try {
        const out = await patchBrandingApi({ appGlyphIcon: lucideName })
        const merged = patchBranding(null, out)
        queryClient.setQueryData(['branding', 'config'], merged)

        const layoutPayload = layoutDraftToApiPayload({ ...useLayoutStore.getState() })
        const withLayout = mergeBrandingWithGlobalLayout(merged, layoutPayload, { stripTheme: true })
        const finalized = patchBranding(null, withLayout)
        applyBrandingCss(finalized)
        useAppStore.getState().setBranding(finalized)
        queryClient.setQueryData(['branding'], finalized)

        setLocalBranding(merged)
      } catch {
        /* silent */
      }
    },
    [queryClient],
  )

  useEffect(() => {
    if (!glyphMenu) return
    const onDown = (e) => {
      if (glyphMenuRef.current?.contains(e.target)) return
      setGlyphMenu(null)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setGlyphMenu(null)
    }
    document.addEventListener('pointerdown', onDown, true)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [glyphMenu])

  async function saveBrandingMeta() {
    setBrandingSaveError(null)
    const body = {
      title: localBranding.title ?? '',
      subtitle: localBranding.subtitle ?? '',
    }
    try {
      const out = await patchBrandingApi(body)
      const merged = patchBranding(null, out)
      setLocalBranding(merged)
      pushBrandingPreview(merged)
      await queryClient.invalidateQueries({ queryKey: ['branding', 'config'] })
      await queryClient.invalidateQueries({ queryKey: ['branding'] })

      try {
        await fetchBranding()
      } catch {
        /* Store already updated by pushBrandingPreview */
      }
      setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))

      const snap = useAppStore.getState().branding
      if (snap && typeof snap === 'object') {
        queryClient.setQueryData(['branding'], snap)
      }
    } catch (e) {
      const msg = e && typeof e === 'object' && 'message' in e ? String(e.message) : String(e)
      setBrandingSaveError(msg || 'Could not save branding.')
    }
  }

  async function onAssetPick(slot, e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !file.type.startsWith('image/')) return
    try {
      const result = await uploadBrandingAsset(slot, file)
      const key = `${slot}Url`
      if (result && typeof result[key] === 'string') updateBrandingField({ [key]: result[key] })
    } catch {
      /* silent */
    }
  }

  async function onRemoveAsset(slot) {
    try {
      await deleteBrandingAsset(slot)
      updateBrandingField({ [`${slot}Url`]: '' })
    } catch {
      /* silent */
    }
  }

  async function saveGlobalToApi(partial) {
    await useLayoutStore.getState().saveLayout(partial)
    try {
      localStorage.removeItem('workspace_layout')
    } catch {
      /* ignore */
    }
    clearWorkspaceLayoutLiveDraft()
    await queryClient.invalidateQueries({ queryKey: ['branding'] })
    await fetchBranding()
  }

  async function saveColors() {
    const body = Object.fromEntries(
      COLOR_KEYS.map(([k]) => [k, localBranding[k] ?? brandingDefaults[k]]),
    )
    const out = await patchBrandingApi(body)
    const merged = patchBranding(null, out)
    setLocalBranding(merged)
    pushBrandingPreview(merged)
    await queryClient.invalidateQueries({ queryKey: ['branding', 'config'] })
    await queryClient.invalidateQueries({ queryKey: ['branding'] })
    await fetchBranding()
  }

  async function saveTypography() {
    const base = clampTypographyFs(globalDraft.fontSize)
    const bodyName = FONT_BODY_OPTIONS.includes(globalDraft.fontBody) ? globalDraft.fontBody : 'Rajdhani'
    const monoName = FONT_MONO_OPTIONS.includes(globalDraft.fontMono) ? globalDraft.fontMono : 'Fira Code'
    await saveGlobalToApi({
      fontBody: bodyName,
      fontMono: monoName,
      fontFamily: FONT_BODY_STACKS[bodyName] || FONT_BODY_STACKS.Rajdhani,
      fontSize: base,
      fsNav: clampTypographyFs(globalDraft.fsNav),
      fsChat: clampTypographyFs(globalDraft.fsChat),
      fsInput: clampTypographyFs(globalDraft.fsInput),
      fsHeading: clampTypographyFs(globalDraft.fsHeading),
      fsCode: clampTypographyFs(globalDraft.fsCode),
    })
    setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
  }

  async function saveLayoutPrefs() {
    await saveGlobalToApi({
      sidebarWidth: Number(globalDraft.sidebarWidth) || 260,
      chatMaxWidth: Number(globalDraft.chatMaxWidth) || 1200,
    })
    setGlobalDraft(layoutDraftToApiPayload({ ...useLayoutStore.getState() }))
  }

  const fontSizeBase = clampTypographyFs(globalDraft.fontSize ?? globalDraft.fontSizeBase ?? 15)
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

      {glyphMenu
        ? createPortal(
            <div
              ref={glyphMenuRef}
              className="fixed z-[200] max-h-[min(70vh,22rem)] min-w-44 overflow-y-auto rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-md"
              style={{ left: glyphMenu.x, top: glyphMenu.y }}
              role="menu"
              aria-label="Choose app icon"
            >
              <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">App icon</div>
              {GLYPH_PICKER_ICONS.map((name) => {
                const G = lucideGlyphComponent(name, 'Circle')
                return (
                  <button
                    key={name}
                    type="button"
                    role="menuitem"
                    className="relative flex w-full cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none hover:bg-accent hover:text-accent-foreground focus:bg-accent focus:text-accent-foreground"
                    onClick={() => void persistAppGlyphIcon(name)}
                  >
                    <G className="size-4 shrink-0" aria-hidden />
                    <span>{name}</span>
                  </button>
                )
              })}
            </div>,
            document.body,
          )
        : null}

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="shrink-0 overflow-x-auto border-b border-border" role="tablist" aria-label="Settings sections">
          <div className="flex flex-row">
            {settingsTabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
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

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6">
          {tab === 'branding' && (
            <section className="mx-auto w-full max-w-2xl space-y-3">
              <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">
                Branding
              </h2>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Title</span>
                <input
                  value={localBranding.title ?? ''}
                  onChange={(e) => updateBrandingField({ title: e.target.value })}
                  className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Slogan (landing)</span>
                <span className="text-xs text-muted-foreground">
                  Shown under the title on the home page. Save branding to apply.
                </span>
                <input
                  value={localBranding.subtitle ?? ''}
                  onChange={(e) => updateBrandingField({ subtitle: e.target.value })}
                  className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
                  placeholder="// your line here"
                />
              </label>
              <div className="flex flex-col gap-2 text-sm">
                <span className="text-muted-foreground">Banner</span>
                <input type="file" accept="image/*" className="text-xs" onChange={(e) => void onAssetPick('banner', e)} />
                {localBranding.bannerUrl ? (
                  <div className="flex flex-wrap items-start gap-2">
                    <img src={localBranding.bannerUrl} alt="" className="max-h-24 rounded-md border border-border object-contain" />
                    <Button type="button" variant="outline" size="sm" onClick={() => void onRemoveAsset('banner')}>
                      Remove
                    </Button>
                  </div>
                ) : null}
              </div>
              <div className="flex flex-col gap-2 text-sm">
                <span className="text-muted-foreground">Logo</span>
                <input type="file" accept="image/*" className="text-xs" onChange={(e) => void onAssetPick('logo', e)} />
                {localBranding.logoUrl ? (
                  <div className="flex flex-wrap items-start gap-2">
                    <img src={localBranding.logoUrl} alt="" className="max-h-16 w-auto rounded-md border border-border object-contain" />
                    <Button type="button" variant="outline" size="sm" onClick={() => void onRemoveAsset('logo')}>
                      Remove
                    </Button>
                  </div>
                ) : null}
              </div>
              <div className="flex flex-col gap-2 text-sm">
                <span className="text-muted-foreground">Favicon</span>
                <input type="file" accept="image/*" className="text-xs" onChange={(e) => void onAssetPick('favicon', e)} />
                {localBranding.faviconUrl ? (
                  <div className="flex flex-wrap items-start gap-2">
                    <img src={localBranding.faviconUrl} alt="" className="size-8 rounded border border-border object-contain" />
                    <Button type="button" variant="outline" size="sm" onClick={() => void onRemoveAsset('favicon')}>
                      Remove
                    </Button>
                  </div>
                ) : null}
              </div>
              <Button type="button" size="sm" onClick={() => void saveBrandingMeta()}>
                Save branding
              </Button>
              {brandingSaveError ? (
                <p className="text-sm text-destructive" role="alert">
                  {brandingSaveError}
                </p>
              ) : null}
            </section>
          )}

          {tab === 'colors' && (
            <section className="mx-auto w-full max-w-2xl space-y-3">
              <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">
                Colors
              </h2>
              <p className="text-sm text-muted-foreground">
                Theme tokens for the workspace. Typography and layout below stay shared.
              </p>
              <div className="flex flex-col gap-3">
                {COLOR_KEYS.map(([key, label]) => (
                  <label key={key} className="flex items-center gap-2 text-sm">
                    <span className="w-28 shrink-0 text-muted-foreground">{label}</span>
                    <input
                      type="color"
                      value={
                        /^#[0-9A-Fa-f]{6}$/.test(String(localBranding[key] || ''))
                          ? localBranding[key]
                          : brandingDefaults[key] || '#000000'
                      }
                      onChange={(e) => updateBrandingField({ [key]: e.target.value })}
                      className="h-9 w-12 cursor-pointer rounded border border-border bg-background"
                    />
                    <input
                      value={localBranding[key] ?? ''}
                      onChange={(e) => updateBrandingField({ [key]: e.target.value })}
                      className="h-9 min-w-0 flex-1 rounded-md border border-border bg-background px-2 font-mono text-xs text-foreground outline-none ring-ring focus-visible:ring-2"
                      placeholder="#000000"
                    />
                  </label>
                ))}
              </div>
              <Button type="button" size="sm" onClick={() => void saveColors()}>
                Save colors
              </Button>
            </section>
          )}

          {tab === 'typography' && (
            <section className="mx-auto w-full max-w-2xl space-y-6">
              <h2 className="fs-heading font-semibold uppercase tracking-wide text-muted-foreground">Typography (global)</h2>
              <p className="text-sm text-muted-foreground">Applies to the workspace.</p>

              <div className="space-y-3">
                <h3 className="text-sm font-medium text-foreground">Font family</h3>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Body font</span>
                  <select
                    className={selectClass}
                    value={
                      FONT_BODY_OPTIONS.includes(globalDraft.fontBody) ? globalDraft.fontBody : 'Rajdhani'
                    }
                    onChange={(e) => {
                      const fontBody = e.target.value
                      updateGlobalDraft({
                        fontBody,
                        fontFamily: FONT_BODY_STACKS[fontBody] ?? globalDraft.fontFamily,
                      })
                    }}
                  >
                    {FONT_BODY_OPTIONS.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Mono font</span>
                  <select
                    className={selectClass}
                    value={
                      FONT_MONO_OPTIONS.includes(globalDraft.fontMono) ? globalDraft.fontMono : 'Fira Code'
                    }
                    onChange={(e) => updateGlobalDraft({ fontMono: e.target.value })}
                  >
                    {FONT_MONO_OPTIONS.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

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

              <Button type="button" size="sm" onClick={() => void saveTypography()}>
                Save typography
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
              <Button type="button" size="sm" onClick={() => void saveLayoutPrefs()}>
                Save layout
              </Button>

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

          {tab === 'search' && <SearchSettingsTab />}

          {tab === 'skills' && <SkillsLibraryPage />}
        </div>
      </div>
    </div>
  )
}
