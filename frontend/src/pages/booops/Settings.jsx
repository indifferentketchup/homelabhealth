import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'

import {
  DEFAULT_BOOOPS_BRANDING,
  FONT_BODY_OPTIONS,
  FONT_BODY_STACKS,
  FONT_MONO_OPTIONS,
  applyBrandingCss,
  deleteBrandingAsset,
  fetchBranding,
  patchBranding,
  updateBranding,
  uploadBrandingAsset,
} from '@/api/branding.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'

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

export default function BooOpsSettings() {
  const queryClient = useQueryClient()
  const settingsOpen = useAppStore((s) => s.settingsOpen)
  const setSettingsOpen = useAppStore((s) => s.setSettingsOpen)

  const initRef = useRef(false)

  const { data } = useQuery({
    queryKey: ['branding', 'booops'],
    queryFn: () => fetchBranding('booops'),
    staleTime: 60_000,
    enabled: settingsOpen,
  })

  const [local, setLocal] = useState(() => ({ ...DEFAULT_BOOOPS_BRANDING }))

  const pushPreview = useCallback(
    (next) => {
      const merged = patchBranding(null, next)
      applyBrandingCss(merged, 'booops')
      queryClient.setQueryData(['branding', 'booops'], merged)
    },
    [queryClient],
  )

  const handleClose = useCallback(async () => {
    setSettingsOpen(false)
    await queryClient.refetchQueries({ queryKey: ['branding', 'booops'] })
    const fresh = queryClient.getQueryData(['branding', 'booops'])
    if (fresh) applyBrandingCss(fresh, 'booops')
  }, [queryClient, setSettingsOpen])

  const updateField = useCallback(
    (patch) => {
      setLocal((prev) => {
        const next = { ...prev, ...patch }
        const merged = patchBranding(null, next)
        applyBrandingCss(merged, 'booops')
        queryClient.setQueryData(['branding', 'booops'], merged)
        return next
      })
    },
    [queryClient],
  )

  useEffect(() => {
    if (!settingsOpen) {
      initRef.current = false
      return
    }
    if (data && !initRef.current) {
      setLocal(patchBranding(null, data))
      initRef.current = true
    }
  }, [settingsOpen, data])

  useEffect(() => {
    if (!settingsOpen) return
    function onKey(e) {
      if (e.key === 'Escape') void handleClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [settingsOpen, handleClose])

  async function saveBrandingMeta() {
    const body = {
      title: local.title ?? '',
      subtitle: local.subtitle ?? '',
    }
    const out = await updateBranding(body)
    setLocal(patchBranding(null, out))
    pushPreview(out)
    await queryClient.invalidateQueries({ queryKey: ['branding', 'booops'] })
  }

  async function saveColors() {
    const body = Object.fromEntries(COLOR_KEYS.map(([k]) => [k, local[k]]))
    const out = await updateBranding(body)
    setLocal(patchBranding(null, out))
    pushPreview(out)
    await queryClient.invalidateQueries({ queryKey: ['branding', 'booops'] })
  }

  async function saveTypography() {
    const base = clampTypographyFs(local.fontSizeBase ?? local.baseFontSize)
    const pb = patchBranding(null, local)
    const bodyName = FONT_BODY_OPTIONS.includes(local.fontBody) ? local.fontBody : pb.fontBody
    const monoName = FONT_MONO_OPTIONS.includes(local.fontMono) ? local.fontMono : pb.fontMono
    const body = {
      fontBody: bodyName,
      fontMono: monoName,
      fontFamily: FONT_BODY_STACKS[bodyName] || local.fontFamily || FONT_BODY_STACKS.Rajdhani,
      fontSizeBase: base,
      baseFontSize: base,
      fsNav: clampTypographyFs(local.fsNav),
      fsChat: clampTypographyFs(local.fsChat),
      fsInput: clampTypographyFs(local.fsInput),
      fsHeading: clampTypographyFs(local.fsHeading),
      fsCode: clampTypographyFs(local.fsCode),
    }
    const out = await updateBranding(body)
    setLocal(patchBranding(null, out))
    pushPreview(out)
    await queryClient.invalidateQueries({ queryKey: ['branding', 'booops'] })
  }

  async function saveLayout() {
    const body = {
      sidebarWidth: Number(local.sidebarWidth) || DEFAULT_BOOOPS_BRANDING.sidebarWidth,
      chatMaxWidth: Number(local.chatMaxWidth) || DEFAULT_BOOOPS_BRANDING.chatMaxWidth,
    }
    const out = await updateBranding(body)
    setLocal(patchBranding(null, out))
    pushPreview(out)
    await queryClient.invalidateQueries({ queryKey: ['branding', 'booops'] })
  }

  async function onAssetPick(slot, e) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file || !file.type.startsWith('image/')) return
    try {
      const result = await uploadBrandingAsset(slot, file)
      const key = `${slot}Url`
      if (result && typeof result[key] === 'string') {
        updateField({ [key]: result[key] })
      }
    } catch {
      /* silent */
    }
  }

  async function onRemoveAsset(slot) {
    try {
      await deleteBrandingAsset(slot)
      updateField({ [`${slot}Url`]: '' })
    } catch {
      /* silent */
    }
  }

  if (!settingsOpen) return null

  const fontSizeBase = clampTypographyFs(local.fontSizeBase ?? local.baseFontSize)
  const sidebarWidth = Number(local.sidebarWidth) || 260
  const chatMaxWidth = Number(local.chatMaxWidth) || DEFAULT_BOOOPS_BRANDING.chatMaxWidth

  return (
    <>
      <button
        type="button"
        className="fixed inset-0 z-[9998] bg-background/60"
        aria-label="Close settings"
        onClick={() => void handleClose()}
      />
      <aside
        className="fixed bottom-0 right-0 top-0 z-[9999] flex w-[420px] max-w-[100vw] flex-col border-l border-border bg-card text-card-foreground shadow-xl"
        role="dialog"
        aria-modal="true"
        aria-labelledby="booops-settings-title"
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 id="booops-settings-title" className="text-sm font-semibold tracking-tight">
            Settings
          </h2>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => void handleClose()}>
            <X className="size-4" />
            <span className="sr-only">Close</span>
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <section className="mb-8 space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Branding</h3>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Title</span>
              <input
                value={local.title ?? ''}
                onChange={(e) => updateField({ title: e.target.value })}
                className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Subtitle</span>
              <input
                value={local.subtitle ?? ''}
                onChange={(e) => updateField({ subtitle: e.target.value })}
                className="h-9 rounded-md border border-border bg-background px-2 text-foreground outline-none ring-ring focus-visible:ring-2"
              />
            </label>
            <div className="flex flex-col gap-2 text-sm">
              <span className="text-muted-foreground">Banner</span>
              <input type="file" accept="image/*" className="text-xs" onChange={(e) => void onAssetPick('banner', e)} />
              {local.bannerUrl ? (
                <div className="flex flex-wrap items-start gap-2">
                  <img src={local.bannerUrl} alt="" className="max-h-24 rounded-md border border-border object-contain" />
                  <Button type="button" variant="outline" size="sm" onClick={() => void onRemoveAsset('banner')}>
                    Remove
                  </Button>
                </div>
              ) : null}
            </div>
            <div className="flex flex-col gap-2 text-sm">
              <span className="text-muted-foreground">Logo</span>
              <input type="file" accept="image/*" className="text-xs" onChange={(e) => void onAssetPick('logo', e)} />
              {local.logoUrl ? (
                <div className="flex flex-wrap items-start gap-2">
                  <img src={local.logoUrl} alt="" className="max-h-16 w-auto rounded-md border border-border object-contain" />
                  <Button type="button" variant="outline" size="sm" onClick={() => void onRemoveAsset('logo')}>
                    Remove
                  </Button>
                </div>
              ) : null}
            </div>
            <div className="flex flex-col gap-2 text-sm">
              <span className="text-muted-foreground">Favicon</span>
              <input type="file" accept="image/*" className="text-xs" onChange={(e) => void onAssetPick('favicon', e)} />
              {local.faviconUrl ? (
                <div className="flex flex-wrap items-start gap-2">
                  <img src={local.faviconUrl} alt="" className="size-8 rounded border border-border object-contain" />
                  <Button type="button" variant="outline" size="sm" onClick={() => void onRemoveAsset('favicon')}>
                    Remove
                  </Button>
                </div>
              ) : null}
            </div>
            <Button type="button" size="sm" onClick={() => void saveBrandingMeta()}>
              Save branding
            </Button>
          </section>

          <section className="mb-8 space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Colors</h3>
            <div className="flex flex-col gap-3">
              {COLOR_KEYS.map(([key, label]) => (
                <label key={key} className="flex items-center gap-2 text-sm">
                  <span className="w-28 shrink-0 text-muted-foreground">{label}</span>
                  <input
                    type="color"
                    value={
                      /^#[0-9A-Fa-f]{6}$/.test(String(local[key] || ''))
                        ? local[key]
                        : DEFAULT_BOOOPS_BRANDING[key] || '#000000'
                    }
                    onChange={(e) => updateField({ [key]: e.target.value })}
                    className="h-9 w-12 cursor-pointer rounded border border-border bg-background"
                  />
                  <input
                    value={local[key] ?? ''}
                    onChange={(e) => updateField({ [key]: e.target.value })}
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

          <section className="mb-8 space-y-6">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Typography</h3>
            <div className="space-y-3">
              <h4 className="text-sm font-medium text-foreground">Font family</h4>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Body font</span>
                <select
                  className={selectClass}
                  value={FONT_BODY_OPTIONS.includes(local.fontBody) ? local.fontBody : patchBranding(null, local).fontBody}
                  onChange={(e) => {
                    const fontBody = e.target.value
                    updateField({
                      fontBody,
                      fontFamily: FONT_BODY_STACKS[fontBody] ?? local.fontFamily,
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
                  value={FONT_MONO_OPTIONS.includes(local.fontMono) ? local.fontMono : patchBranding(null, local).fontMono}
                  onChange={(e) => updateField({ fontMono: e.target.value })}
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
              <h4 className="text-sm font-medium text-foreground">Font sizes</h4>
              <FontSizeRow
                label="Base"
                value={fontSizeBase}
                onChange={(n) => updateField({ fontSizeBase: n, baseFontSize: n })}
              />
              <FontSizeRow label="Nav / sidebar" value={local.fsNav} onChange={(n) => updateField({ fsNav: n })} />
              <FontSizeRow label="Chat messages" value={local.fsChat} onChange={(n) => updateField({ fsChat: n })} />
              <FontSizeRow label="Chat input" value={local.fsInput} onChange={(n) => updateField({ fsInput: n })} />
              <FontSizeRow label="Headings" value={local.fsHeading} onChange={(n) => updateField({ fsHeading: n })} />
              <FontSizeRow label="Code blocks" value={local.fsCode} onChange={(n) => updateField({ fsCode: n })} />
            </div>
            <Button type="button" size="sm" onClick={() => void saveTypography()}>
              Save typography
            </Button>
          </section>

          <section className="mb-4 space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Layout</h3>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Sidebar width ({sidebarWidth}px)</span>
              <input
                type="range"
                min={200}
                max={400}
                step={1}
                value={sidebarWidth}
                onChange={(e) => updateField({ sidebarWidth: Number(e.target.value) })}
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
                onChange={(e) => updateField({ chatMaxWidth: Number(e.target.value) })}
                className="w-full"
              />
            </label>
            <Button type="button" size="sm" onClick={() => void saveLayout()}>
              Save layout
            </Button>
          </section>
        </div>
      </aside>
    </>
  )
}
