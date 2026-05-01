import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import * as LucideIcons from 'lucide-react'

import {
  DEFAULT_BOOLAB_BRANDING,
  fetchBoolabBranding,
  injectHubGoogleFonts,
  patchBoolabBranding,
} from '@/api/branding.js'
import {
  PATH_BOOLAB,
  PATH_808NOTES_HOME,
  PATH_BOOCODE_HOME,
  PATH_BOOOPS_HOME,
  get808notesPublicHref,
  getBoocodePublicHref,
  getBooopsPublicHref,
  isHttpUrl,
} from '@/routes/paths.js'
import { cn } from '@/lib/utils'
import { useAppStore } from '@/store/index.js'

function HubLucide({ name, className, style }) {
  const C =
    LucideIcons[name] && typeof LucideIcons[name] === 'function'
      ? LucideIcons[name]
      : LucideIcons.Circle
  return <C className={className} style={style} aria-hidden />
}

export default function BoolabLanding() {
  const currentUser = useAppStore((s) => s.currentUser)
  const [fontReady, setFontReady] = useState(false)
  const { data, isError } = useQuery({
    queryKey: ['branding', 'boolab'],
    queryFn: fetchBoolabBranding,
    staleTime: 60_000,
  })

  const merged = patchBoolabBranding(
    null,
    !isError && data ? data : DEFAULT_BOOLAB_BRANDING,
  )

  useEffect(() => {
    injectHubGoogleFonts(merged.hubDisplayFont, merged.hubMonoFont)
  }, [merged.hubDisplayFont, merged.hubMonoFont])

  useEffect(() => {
    let cancelled = false
    setFontReady(false)
    if (typeof document !== 'undefined' && document.fonts?.ready) {
      document.fonts.ready.then(() => {
        if (!cancelled) setFontReady(true)
      })
    } else {
      setFontReady(true)
    }
    return () => {
      cancelled = true
    }
  }, [merged.hubDisplayFont, merged.hubMonoFont])

  useEffect(() => {
    const t = typeof merged.title === 'string' && merged.title.trim() ? merged.title.trim() : 'BooLab'
    document.title = t
    const fav = merged.faviconUrl
    if (typeof fav === 'string' && fav.trim()) {
      let link = document.querySelector("link[rel~='icon']")
      if (!link) {
        link = document.createElement('link')
        link.rel = 'icon'
        document.head.appendChild(link)
      }
      link.href = fav.trim()
    }
  }, [merged.title, merged.faviconUrl])

  const boo = merged.booopsCard || DEFAULT_BOOLAB_BRANDING.booopsCard
  const notes = merged.notes808Card || DEFAULT_BOOLAB_BRANDING.notes808Card
  const code = merged.boocodeCard || DEFAULT_BOOLAB_BRANDING.boocodeCard
  const displayStack = merged.hubDisplayFont ? `'${merged.hubDisplayFont}', monospace` : undefined
  const monoStack = merged.hubMonoFont ? `'${merged.hubMonoFont}', monospace` : undefined
  const landingFontScale = clampHubLandingFontScale(merged.hubLandingFontScale)
  const landingIconScale = clampHubLandingIconScale(merged.hubLandingIconScale)

  const hubStyle = {
    '--hub-accent': merged.accentColor,
    '--hub-bg': merged.bgColor,
    '--hub-bg1': merged.bgPanel,
    '--hub-bg2': merged.bgCard,
    '--hub-text': merged.textColor,
    '--hub-text2': merged.textDim,
    '--hub-text3': 'rgba(90, 120, 100, 0.45)',
    '--hub-border': merged.borderColor,
    '--hub-border2': `color-mix(in srgb, ${merged.accentColor || '#5dcf8f'} 28%, transparent)`,
    '--hub-page-max': '960px',
    '--hub-landing-fs': String(landingFontScale),
    '--hub-landing-is': String(landingIconScale),
    '--hub-logo-w': `${Math.round(72 * landingIconScale)}px`,
    '--hub-logo-w-sm': `${Math.round(96 * landingIconScale)}px`,
    '--hub-logo-w-lg': `${Math.round(120 * landingIconScale)}px`,
  }

  return (
    <div className="boolab-hub flex min-h-[100dvh] flex-col" style={hubStyle}>
      <div
        className="boolab-hub-corner left-[14px] top-[14px] border-l border-t"
        style={{ borderColor: 'color-mix(in srgb, var(--hub-accent) 28%, transparent)' }}
      />
      <div
        className="boolab-hub-corner right-[14px] top-[14px] border-r border-t"
        style={{ borderColor: 'color-mix(in srgb, var(--hub-accent) 28%, transparent)' }}
      />
      <div
        className="boolab-hub-corner bottom-[14px] left-[14px] border-b border-l"
        style={{ borderColor: 'color-mix(in srgb, var(--hub-accent) 28%, transparent)' }}
      />
      <div
        className="boolab-hub-corner bottom-[14px] right-[14px] border-b border-r"
        style={{ borderColor: 'color-mix(in srgb, var(--hub-accent) 28%, transparent)' }}
      />

      <div
        className="relative z-10 mx-auto flex w-full flex-1 flex-col px-4 md:px-8"
        style={{ maxWidth: 'var(--hub-page-max)' }}
      >
        <div
          className="relative mt-0 aspect-[3/1] w-full overflow-hidden border-b"
          style={{ borderColor: 'var(--hub-border2)' }}
        >
          {merged.bannerUrl ? (
            <img
              src={merged.bannerUrl}
              alt=""
              className="h-full w-full object-cover"
              style={{ filter: 'saturate(1.05) brightness(0.55)' }}
            />
          ) : (
            <div
              className="flex h-full w-full items-center justify-center"
              style={{
                background: [
                  'radial-gradient(ellipse at 28% 50%, color-mix(in srgb, var(--hub-accent) 28%, transparent), transparent 58%)',
                  'radial-gradient(ellipse at 72% 45%, color-mix(in srgb, var(--hub-accent) 14%, transparent), transparent 55%)',
                  'var(--hub-bg1)',
                ].join(','),
              }}
            >
              <span
                className="boolab-hub-landing-mono-sm border px-[18px] py-2 uppercase tracking-[0.25em]"
                style={{
                  borderColor: 'var(--hub-border)',
                  color: 'var(--hub-text3)',
                  fontFamily: monoStack || 'var(--font-mono)',
                }}
              >
                // boolab
              </span>
            </div>
          )}
          <div className="boolab-hub-banner-grid pointer-events-none" aria-hidden />
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background: `linear-gradient(to bottom, transparent 30%, ${merged.bgColor} 100%)`,
            }}
          />
        </div>

        <header
          className={cn(
            'relative z-10 -mt-12 px-0 pb-6 pt-2 sm:-mt-16 md:-mt-20 md:pb-8',
          )}
        >
          <div className="flex flex-wrap items-end gap-4 md:gap-6">
            <div
              className="boolab-hub-logo-tile flex shrink-0 items-center justify-center overflow-hidden rounded-xl border shadow-lg md:rounded-[22px]"
              style={{
                borderColor: 'color-mix(in srgb, var(--hub-accent) 45%, transparent)',
                boxShadow: `0 0 40px ${'color-mix(in srgb, var(--hub-accent) 35%, transparent)'}, 0 0 100px color-mix(in srgb, var(--hub-accent) 12%, transparent)`,
                background: 'var(--hub-bg2)',
              }}
            >
              {merged.logoUrl ? (
                <img src={merged.logoUrl} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full w-full items-center justify-center p-2">
                  <HubLucide
                    name={merged.appGlyphIcon || 'FlaskConical'}
                    className="boolab-hub-hero-glyph"
                    style={{
                      color: 'var(--hub-accent)',
                      filter:
                        'drop-shadow(0 0 10px color-mix(in srgb, var(--hub-accent) 50%, transparent))',
                    }}
                  />
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1 pb-1">
              <h1
                className={cn(
                  'boolab-hub-hero-title mb-2 font-extrabold leading-none tracking-wide',
                  fontReady ? 'opacity-100' : 'opacity-0',
                )}
                style={{
                  fontFamily: displayStack || 'monospace',
                  color: 'var(--hub-accent)',
                  textShadow:
                    '0 0 12px var(--hub-accent-glow), 0 0 40px color-mix(in srgb, var(--hub-accent) 25%, transparent)',
                  transition: 'opacity 0.25s ease',
                }}
              >
                {merged.title || 'BooLab'}
              </h1>
              <p
                className="boolab-hub-hero-tagline tracking-[0.16em]"
                style={{ fontFamily: monoStack || 'var(--font-mono)', color: 'var(--hub-text2)' }}
              >
                {merged.tagline || ''}
              </p>
            </div>
          </div>
        </header>

        <main className="relative z-10 flex min-h-0 flex-1 flex-col pb-6">
          <div className="mb-3 flex items-center gap-2.5">
            <span
              className="h-px w-5 shrink-0"
              style={{
                background: 'var(--hub-accent)',
                boxShadow: '0 0 4px var(--hub-accent-glow)',
              }}
            />
            <span
              className="boolab-hub-landing-label uppercase tracking-[0.22em]"
              style={{ fontFamily: monoStack || 'var(--font-mono)', color: 'var(--hub-text3)' }}
            >
              core
            </span>
            <span className="h-px flex-1" style={{ background: 'var(--hub-border)' }} />
          </div>

          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 md:gap-4">
            <HubAppCard
              publicHref={getBooopsPublicHref()}
              fallbackTo={PATH_BOOOPS_HOME}
              card={boo}
              landingIconScale={landingIconScale}
              monoStack={monoStack}
              displayStack={displayStack}
              textAlign={merged.hubCardsTextAlign}
              fontScale={merged.hubCardsFontScale}
            />
            <HubAppCard
              publicHref={get808notesPublicHref()}
              fallbackTo={PATH_808NOTES_HOME}
              card={notes}
              landingIconScale={landingIconScale}
              monoStack={monoStack}
              displayStack={displayStack}
              textAlign={merged.hubCardsTextAlign}
              fontScale={merged.hubCardsFontScale}
            />
            <HubAppCard
              publicHref={getBoocodePublicHref()}
              fallbackTo={PATH_BOOCODE_HOME}
              card={code}
              landingIconScale={landingIconScale}
              monoStack={monoStack}
              displayStack={displayStack}
              textAlign={merged.hubCardsTextAlign}
              fontScale={merged.hubCardsFontScale}
            />
          </div>
        </main>
      </div>

      <footer
        className="relative z-10 flex flex-wrap items-center justify-center gap-3 border-t px-4 py-5 md:justify-end md:px-8"
        style={{
          borderColor: 'var(--hub-border)',
          maxWidth: 'var(--hub-page-max)',
          marginInline: 'auto',
          width: '100%',
        }}
      >
        {currentUser?.role === 'owner' ? (
          <>
            <Link
              to={`${PATH_BOOLAB}/ai`.replace(/\/{2,}/g, '/')}
              className="boolab-hub-landing-mono-sm rounded-md border px-4 py-2 uppercase tracking-[0.12em] transition-colors hover:border-[var(--hub-accent)] hover:text-[var(--hub-accent)]"
              style={{
                fontFamily: monoStack || 'var(--font-mono)',
                borderColor: 'var(--hub-border2, var(--hub-border))',
                background: 'var(--hub-bg2)',
                color: 'var(--hub-text2)',
              }}
            >
              AI settings
            </Link>
            <Link
              to={`${PATH_BOOLAB}/branding`.replace(/\/{2,}/g, '/')}
              className="boolab-hub-landing-mono-sm rounded-md border px-4 py-2 uppercase tracking-[0.12em] transition-colors hover:border-[var(--hub-accent)] hover:text-[var(--hub-accent)]"
              style={{
                fontFamily: monoStack || 'var(--font-mono)',
                borderColor: 'var(--hub-border2, var(--hub-border))',
                background: 'var(--hub-bg2)',
                color: 'var(--hub-text2)',
              }}
            >
              Branding settings
            </Link>
          </>
        ) : null}
      </footer>
    </div>
  )
}

const HUB_CARD_ALIGN = new Set(['center', 'start', 'end'])

function clampHubLandingFontScale(n) {
  const x = typeof n === 'number' ? n : Number(n)
  if (!Number.isFinite(x)) return 1
  return Math.min(1.5, Math.max(0.75, x))
}

function clampHubLandingIconScale(n) {
  const x = typeof n === 'number' ? n : Number(n)
  if (!Number.isFinite(x)) return 1
  return Math.min(1.35, Math.max(0.75, x))
}

function clampHubCardScale(n) {
  const x = typeof n === 'number' ? n : Number(n)
  if (!Number.isFinite(x)) return 1
  return Math.min(1.5, Math.max(0.75, x))
}

function clampHubCardIconBasePx(n) {
  const x = typeof n === 'number' ? n : Number(n)
  if (!Number.isFinite(x)) return 48
  return Math.min(120, Math.max(24, Math.round(x)))
}

function HubAppCard({ publicHref, fallbackTo, card, monoStack, displayStack, textAlign, fontScale, landingIconScale }) {
  const accent = card?.accent || 'var(--hub-accent)'
  const align = HUB_CARD_ALIGN.has(textAlign) ? textAlign : 'center'
  const scale = clampHubCardScale(fontScale)
  const li = clampHubLandingIconScale(landingIconScale)
  const titlePx = Math.round(18 * scale)
  const descPx = Math.round(15 * scale)
  const iconBase = clampHubCardIconBasePx(card?.iconSize)
  const iconPx = Math.round(iconBase * scale * li)
  const iconSrc = typeof card?.iconUrl === 'string' ? card.iconUrl.trim() : ''

  const className = cn(
    'group relative flex flex-col overflow-hidden rounded-[10px] border p-5 transition-all duration-150',
    'hover:-translate-y-0.5 hover:shadow-lg',
    'aspect-[2/1] min-h-[140px]',
  )
  const style = {
    borderColor: 'var(--hub-border)',
    background: 'var(--hub-bg2)',
    ['--card-accent']: accent,
    boxShadow: '0 4px 24px rgba(0,0,0,0.35)',
  }

  const outer =
    publicHref && isHttpUrl(publicHref) ? (
      <a
        href={publicHref}
        className={className}
        style={style}
        rel="noopener noreferrer"
      >
        <HubAppCardInner
          align={align}
          card={card}
          descPx={descPx}
          displayStack={displayStack}
          iconPx={iconPx}
          iconSrc={iconSrc}
          monoStack={monoStack}
          scale={scale}
          titlePx={titlePx}
        />
      </a>
    ) : (
      <Link to={fallbackTo} className={className} style={style}>
        <HubAppCardInner
          align={align}
          card={card}
          descPx={descPx}
          displayStack={displayStack}
          iconPx={iconPx}
          iconSrc={iconSrc}
          monoStack={monoStack}
          scale={scale}
          titlePx={titlePx}
        />
      </Link>
    )

  return outer
}

function HubAppCardInner({
  align,
  card,
  descPx,
  displayStack,
  iconPx,
  iconSrc,
  monoStack,
  scale,
  titlePx,
}) {
  return (
    <>
      <span
        className="absolute bottom-0 left-0 top-0 w-[3px] opacity-70 transition-opacity group-hover:opacity-100"
        style={{ background: 'var(--card-accent)' }}
      />
      <div
        className={cn(
          'flex min-h-0 flex-1 flex-col gap-2',
          align === 'center' && 'items-center text-center',
          align === 'start' && 'items-start text-left',
          align === 'end' && 'items-end text-right',
        )}
      >
        {iconSrc ? (
          <img
            src={iconSrc}
            alt=""
            className="shrink-0 object-contain opacity-95 transition-[filter] group-hover:brightness-110"
            style={{
              width: iconPx,
              height: iconPx,
              filter: 'drop-shadow(0 0 8px color-mix(in srgb, var(--card-accent) 45%, transparent))',
            }}
          />
        ) : (
          <HubLucide
            name={card?.icon || 'Circle'}
            className="shrink-0 opacity-95 transition-[filter] group-hover:brightness-110"
            style={{
              width: iconPx,
              height: iconPx,
              color: 'var(--card-accent)',
              filter: 'drop-shadow(0 0 8px color-mix(in srgb, var(--card-accent) 45%, transparent))',
            }}
          />
        )}
        <div className="min-w-0 w-full">
          <div
            className="mb-1 font-bold tracking-wide"
            style={{
              fontFamily: displayStack || 'monospace',
              color: 'var(--hub-text)',
              fontSize: `${titlePx}px`,
            }}
          >
            {card?.title}
          </div>
          <p
            className="line-clamp-2 leading-snug"
            style={{
              fontFamily: 'var(--font-body)',
              color: 'var(--hub-text2)',
              fontSize: `${descPx}px`,
            }}
          >
            {card?.description}
          </p>
        </div>
      </div>
      <div
        className={cn(
          'mt-auto flex w-full pt-2',
          align === 'center' && 'justify-center',
          align === 'start' && 'justify-start',
          align === 'end' && 'justify-end',
        )}
      >
        <span
          className="rounded border uppercase tracking-[0.1em]"
          style={{
            fontFamily: monoStack || 'var(--font-mono)',
            color: 'var(--hub-accent)',
            borderColor: 'color-mix(in srgb, var(--hub-accent) 25%, transparent)',
            textShadow: '0 0 6px color-mix(in srgb, var(--hub-accent) 40%, transparent)',
            fontSize: `${Math.max(9, Math.round(9 * scale))}px`,
            paddingInline: `${Math.round(9 * scale)}px`,
            paddingBlock: `${Math.max(2, Math.round(2 * scale))}px`,
          }}
        >
          open
        </span>
      </div>
    </>
  )
}
