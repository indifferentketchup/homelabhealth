import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import {
  DEFAULT_BOOLAB_BRANDING,
  FONT_HUB_DISPLAY_OPTIONS,
  FONT_MONO_OPTIONS,
  fetchBoolabBranding,
  injectHubGoogleFonts,
  patchBoolabBranding,
  updateBoolabBranding,
  uploadBoolabAsset,
  deleteBoolabAsset,
} from '@/api/branding.js'
import { Button } from '@/components/ui/button'
import { PATH_BOOLAB_HOME } from '@/routes/paths.js'
import { cn } from '@/lib/utils'

/** Boolab hub landing card image uploads (`/api/branding/boolab/upload/...`). */
const HUB_CARD_ICON_SLOT = {
  booopsCard: 'cardBooops',
  notes808Card: 'card808notes',
}

export default function BoolabBranding() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['branding', 'boolab'],
    queryFn: fetchBoolabBranding,
    staleTime: 30_000,
  })

  const [draft, setDraft] = useState(() => DEFAULT_BOOLAB_BRANDING)
  useEffect(() => {
    if (data) setDraft(patchBoolabBranding(null, data))
  }, [data])

  useEffect(() => {
    injectHubGoogleFonts(draft.hubDisplayFont, draft.hubMonoFont)
  }, [draft.hubDisplayFont, draft.hubMonoFont])

  const saveMut = useMutation({
    mutationFn: (patch) => updateBoolabBranding(patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['branding', 'boolab'] })
    },
  })

  function setField(key, value) {
    setDraft((d) => ({ ...d, [key]: value }))
  }

  function setCardField(which, key, value) {
    setDraft((d) => ({
      ...d,
      [which]: { ...d[which], [key]: value },
    }))
  }

  async function onUpload(slot, e) {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const res = await uploadBoolabAsset(slot, file)
      const urlKey = `${slot}Url`
      if (res && typeof res === 'object' && res[urlKey]) {
        setField(urlKey, res[urlKey])
      }
      void qc.invalidateQueries({ queryKey: ['branding', 'boolab'] })
    } catch (err) {
      console.error(err)
      alert(String(err.message || err))
    }
    e.target.value = ''
  }

  async function onRemoveAsset(slot) {
    try {
      await deleteBoolabAsset(slot)
      setField(`${slot}Url`, '')
      void qc.invalidateQueries({ queryKey: ['branding', 'boolab'] })
    } catch (err) {
      console.error(err)
      alert(String(err.message || err))
    }
  }

  async function onUploadCardIcon(which, e) {
    const slot = HUB_CARD_ICON_SLOT[which]
    const file = e.target.files?.[0]
    if (!file || !slot) return
    try {
      const res = await uploadBoolabAsset(slot, file)
      if (res && typeof res[which] === 'object') {
        setDraft((d) => ({ ...d, [which]: { ...d[which], ...res[which] } }))
      }
      void qc.invalidateQueries({ queryKey: ['branding', 'boolab'] })
    } catch (err) {
      console.error(err)
      alert(String(err.message || err))
    }
    e.target.value = ''
  }

  async function onRemoveCardIcon(which) {
    const slot = HUB_CARD_ICON_SLOT[which]
    if (!slot) return
    try {
      await deleteBoolabAsset(slot)
      setCardField(which, 'iconUrl', '')
      void qc.invalidateQueries({ queryKey: ['branding', 'boolab'] })
    } catch (err) {
      console.error(err)
      alert(String(err.message || err))
    }
  }

  function save() {
    saveMut.mutate({
      title: draft.title,
      tagline: draft.tagline,
      hubDisplayFont: draft.hubDisplayFont,
      hubMonoFont: draft.hubMonoFont,
      accentColor: draft.accentColor,
      bgColor: draft.bgColor,
      bgPanel: draft.bgPanel,
      bgCard: draft.bgCard,
      textColor: draft.textColor,
      textDim: draft.textDim,
      borderColor: draft.borderColor,
      appGlyphIcon: draft.appGlyphIcon,
      booopsCard: draft.booopsCard,
      notes808Card: draft.notes808Card,
      hubCardsTextAlign: draft.hubCardsTextAlign,
      hubCardsFontScale: draft.hubCardsFontScale,
      hubLandingFontScale: draft.hubLandingFontScale,
      hubLandingIconScale: draft.hubLandingIconScale,
    })
  }

  const displayStack = draft.hubDisplayFont ? `'${draft.hubDisplayFont}', monospace` : undefined
  const monoStack = draft.hubMonoFont ? `'${draft.hubMonoFont}', monospace` : undefined
  const shellStyle = {
    '--hub-accent': draft.accentColor,
    '--hub-bg': draft.bgColor,
    '--hub-bg1': draft.bgPanel,
    '--hub-bg2': draft.bgCard,
    '--hub-text': draft.textColor,
    '--hub-text2': draft.textDim,
    '--hub-border': draft.borderColor,
    '--hub-border2': `color-mix(in srgb, ${draft.accentColor || '#5dcf8f'} 28%, transparent)`,
  }

  return (
    <div
      className="min-h-[100dvh] px-4 py-8 text-[var(--hub-text)] md:px-8"
      style={{ ...shellStyle, background: draft.bgColor }}
    >
      <div className="mx-auto max-w-xl space-y-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1
              className="text-xl font-bold tracking-wide"
              style={{ fontFamily: displayStack || 'monospace', color: draft.accentColor }}
            >
              Boolab hub branding
            </h1>
            <p className="mt-1 text-xs tracking-wider" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
              // banner, type, colors, cards
            </p>
          </div>
          <Button type="button" variant="outline" className="border-[var(--hub-border)] bg-[var(--hub-bg2)]" asChild>
            <Link to={PATH_BOOLAB_HOME}>← Hub</Link>
          </Button>
        </div>

        {isLoading && !data ? (
          <p className="text-sm" style={{ color: draft.textDim }}>
            Loading…
          </p>
        ) : null}

        <section className="space-y-4 rounded-lg border p-4" style={{ borderColor: 'var(--hub-border)', background: draft.bgPanel }}>
          <h2 className="text-[10px] uppercase tracking-[0.18em]" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
            Site
          </h2>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Title
            </span>
            <input
              className="w-full rounded border px-3 py-2 text-sm outline-none focus:ring-1"
              style={{
                borderColor: 'var(--hub-border)',
                background: draft.bgCard,
                color: draft.textColor,
                ['--tw-ring-color']: draft.accentColor,
              }}
              value={draft.title}
              onChange={(e) => setField('title', e.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Tagline
            </span>
            <input
              className="w-full rounded border px-3 py-2 text-sm outline-none"
              style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
              value={draft.tagline}
              onChange={(e) => setField('tagline', e.target.value)}
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Logo fallback — Lucide icon name (when no logo image)
            </span>
            <input
              className="w-full rounded border px-3 py-2 text-sm outline-none"
              style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
              value={draft.appGlyphIcon}
              onChange={(e) => setField('appGlyphIcon', e.target.value)}
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block space-y-1">
              <span className="text-xs" style={{ color: draft.textDim }}>
                Hub title font (Google)
              </span>
              <select
                className="w-full rounded border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                value={FONT_HUB_DISPLAY_OPTIONS.includes(draft.hubDisplayFont) ? draft.hubDisplayFont : ''}
                onChange={(e) => {
                  const v = e.target.value
                  if (v) setField('hubDisplayFont', v)
                }}
              >
                <option value="">— custom below —</option>
                {FONT_HUB_DISPLAY_OPTIONS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
              <input
                className="mt-1 w-full rounded border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                placeholder="Font family name"
                value={draft.hubDisplayFont}
                onChange={(e) => setField('hubDisplayFont', e.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs" style={{ color: draft.textDim }}>
                Hub mono font
              </span>
              <select
                className="w-full rounded border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                value={FONT_MONO_OPTIONS.includes(draft.hubMonoFont) ? draft.hubMonoFont : ''}
                onChange={(e) => {
                  const v = e.target.value
                  if (v) setField('hubMonoFont', v)
                }}
              >
                <option value="">— custom / type below —</option>
                {FONT_MONO_OPTIONS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
              <input
                className="mt-1 w-full rounded border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                placeholder="e.g. Share Tech Mono"
                value={draft.hubMonoFont}
                onChange={(e) => setField('hubMonoFont', e.target.value)}
              />
            </label>
          </div>
        </section>

        <section className="space-y-4 rounded-lg border p-4" style={{ borderColor: 'var(--hub-border)', background: draft.bgPanel }}>
          <h2 className="text-[10px] uppercase tracking-[0.18em]" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
            Assets (960×320 banner recommended)
          </h2>
          {['banner', 'logo', 'favicon'].map((slot) => (
            <div key={slot} className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="mb-1 block text-xs capitalize" style={{ color: draft.textDim }}>
                  {slot}
                </span>
                <input type="file" accept="image/*" className="max-w-full text-xs" onChange={(e) => onUpload(slot, e)} />
              </label>
              {draft[`${slot}Url`] ? (
                <Button type="button" size="sm" variant="outline" onClick={() => onRemoveAsset(slot)}>
                  Remove
                </Button>
              ) : null}
            </div>
          ))}
        </section>

        <section className="space-y-3 rounded-lg border p-4" style={{ borderColor: 'var(--hub-border)', background: draft.bgPanel }}>
          <h2 className="text-[10px] uppercase tracking-[0.18em]" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
            Colors
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              ['accentColor', 'Accent'],
              ['bgColor', 'Background'],
              ['bgPanel', 'Panel'],
              ['bgCard', 'Card'],
            ].map(([key, label]) => (
              <label key={key} className="flex items-center gap-2">
                <input
                  type="color"
                  className="h-9 w-12 cursor-pointer rounded border"
                  style={{ borderColor: 'var(--hub-border)' }}
                  value={toHexColor(draft[key])}
                  onChange={(e) => setField(key, e.target.value)}
                />
                <span className="text-xs" style={{ color: draft.textDim }}>
                  {label}
                </span>
              </label>
            ))}
          </div>
          {[
            ['textColor', 'Text'],
            ['textDim', 'Text dim'],
            ['borderColor', 'Border'],
          ].map(([key, label]) => (
            <label key={key} className="block space-y-1">
              <span className="text-xs" style={{ color: draft.textDim }}>
                {label} (css)
              </span>
              <input
                className="w-full rounded border px-3 py-2 font-mono text-xs outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                value={draft[key]}
                onChange={(e) => setField(key, e.target.value)}
              />
            </label>
          ))}
        </section>

        {(['booopsCard', 'notes808Card']).map((which, idx) => (
          <section
            key={which}
            className="space-y-3 rounded-lg border p-4"
            style={{ borderColor: 'var(--hub-border)', background: draft.bgPanel }}
          >
            <h2 className="text-[10px] uppercase tracking-[0.18em]" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
              {idx === 0 ? 'BooOps card' : '808notes card'}
            </h2>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="block space-y-1">
                <span className="text-xs" style={{ color: draft.textDim }}>
                  Lucide icon name
                </span>
                <input
                  className="w-full rounded border px-3 py-2 text-sm outline-none"
                  style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                  value={draft[which].icon}
                  onChange={(e) => setCardField(which, 'icon', e.target.value)}
                />
              </label>
              <label className="flex items-center gap-2">
                <span className="text-xs shrink-0" style={{ color: draft.textDim }}>
                  Accent
                </span>
                <input
                  type="color"
                  className="h-9 w-12 cursor-pointer rounded border"
                  style={{ borderColor: 'var(--hub-border)' }}
                  value={toHexColor(draft[which].accent)}
                  onChange={(e) => setCardField(which, 'accent', e.target.value)}
                />
              </label>
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <label className="block">
                <span className="mb-1 block text-xs" style={{ color: draft.textDim }}>
                  Card icon image (optional; overrides Lucide)
                </span>
                <input
                  type="file"
                  accept="image/*"
                  className="max-w-full text-xs"
                  onChange={(e) => onUploadCardIcon(which, e)}
                />
              </label>
              {draft[which].iconUrl ? (
                <Button type="button" size="sm" variant="outline" onClick={() => onRemoveCardIcon(which)}>
                  Remove image
                </Button>
              ) : null}
            </div>
            <label className="block space-y-1">
              <span className="text-xs" style={{ color: draft.textDim }}>
                Icon size ({Math.round(Number(draft[which].iconSize) || 44)}px base; scales with card font slider and landing icon %)
              </span>
              <input
                type="range"
                min={24}
                max={120}
                step={2}
                value={Math.round(
                  Number.isFinite(Number(draft[which].iconSize)) ? Number(draft[which].iconSize) : 44,
                )}
                onChange={(e) => setCardField(which, 'iconSize', Number(e.target.value))}
                className="w-full accent-[var(--hub-accent)]"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs" style={{ color: draft.textDim }}>
                Title
              </span>
              <input
                className="w-full rounded border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                value={draft[which].title}
                onChange={(e) => setCardField(which, 'title', e.target.value)}
              />
            </label>
            <label className="block space-y-1">
              <span className="text-xs" style={{ color: draft.textDim }}>
                Description
              </span>
              <input
                className="w-full rounded border px-3 py-2 text-sm outline-none"
                style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
                value={draft[which].description}
                onChange={(e) => setCardField(which, 'description', e.target.value)}
            />
          </label>
          </section>
        ))}

        <section className="space-y-3 rounded-lg border p-4" style={{ borderColor: 'var(--hub-border)', background: draft.bgPanel }}>
          <h2 className="text-[10px] uppercase tracking-[0.18em]" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
            Hub landing (hero)
          </h2>
          <p className="text-xs leading-snug" style={{ color: draft.textDim }}>
            Tweaks the main hub page only (title, tagline, section labels, footer, banner badge, logo tile, and card icons). Card title and body sizes still use the slider below.
          </p>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Text and labels ({Math.round((Number(draft.hubLandingFontScale) || 1) * 100)}%)
            </span>
            <input
              type="range"
              min={75}
              max={150}
              step={5}
              value={Math.round(
                (Number.isFinite(Number(draft.hubLandingFontScale)) ? Number(draft.hubLandingFontScale) : 1) * 100,
              )}
              onChange={(e) => setField('hubLandingFontScale', Number(e.target.value) / 100)}
              className="w-full accent-[var(--hub-accent)]"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Icons ({Math.round((Number(draft.hubLandingIconScale) || 1) * 100)}%)
            </span>
            <input
              type="range"
              min={75}
              max={135}
              step={5}
              value={Math.round(
                (Number.isFinite(Number(draft.hubLandingIconScale)) ? Number(draft.hubLandingIconScale) : 1) * 100,
              )}
              onChange={(e) => setField('hubLandingIconScale', Number(e.target.value) / 100)}
              className="w-full accent-[var(--hub-accent)]"
            />
          </label>
        </section>

        <section className="space-y-3 rounded-lg border p-4" style={{ borderColor: 'var(--hub-border)', background: draft.bgPanel }}>
          <h2 className="text-[10px] uppercase tracking-[0.18em]" style={{ fontFamily: monoStack || 'var(--font-mono)', color: draft.textDim }}>
            Hub cards (landing)
          </h2>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Text alignment (title, description, icon row, open chip)
            </span>
            <select
              className="w-full rounded border px-3 py-2 text-sm outline-none"
              style={{ borderColor: 'var(--hub-border)', background: draft.bgCard, color: draft.textColor }}
              value={['center', 'start', 'end'].includes(draft.hubCardsTextAlign) ? draft.hubCardsTextAlign : 'center'}
              onChange={(e) => setField('hubCardsTextAlign', e.target.value)}
            >
              <option value="center">Center</option>
              <option value="start">Left</option>
              <option value="end">Right</option>
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-xs" style={{ color: draft.textDim }}>
              Font size ({Math.round((Number(draft.hubCardsFontScale) || 1) * 100)}%)
            </span>
            <input
              type="range"
              min={75}
              max={150}
              step={5}
              value={Math.round((Number.isFinite(Number(draft.hubCardsFontScale)) ? Number(draft.hubCardsFontScale) : 1) * 100)}
              onChange={(e) => setField('hubCardsFontScale', Number(e.target.value) / 100)}
              className="w-full accent-[var(--hub-accent)]"
            />
          </label>
        </section>

        <div className="flex flex-wrap gap-3">
          <Button
            type="button"
            disabled={saveMut.isPending}
            className={cn('font-medium')}
            style={{ background: draft.accentColor, color: draft.bgColor }}
            onClick={save}
          >
            {saveMut.isPending ? 'Saving…' : 'Save'}
          </Button>
          {saveMut.isSuccess ? (
            <span className="self-center text-xs" style={{ color: draft.textDim }}>
              Saved.
            </span>
          ) : null}
          {saveMut.isError ? (
            <span className="self-center text-xs text-red-400">Error — check console</span>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** Hex picker value; non-hex (e.g. rgba) falls back so the input stays usable. */
function toHexColor(val) {
  if (typeof val !== 'string') return '#5dcf8f'
  const s = val.trim()
  if (/^#[0-9a-fA-F]{6}$/.test(s)) return s
  if (/^#[0-9a-fA-F]{3}$/.test(s)) return s
  return '#0d1510'
}
