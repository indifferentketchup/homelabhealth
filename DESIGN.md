---
name: homelabhealth
description: Self-hosted RAG chat for personal health records — calm, warm, trustworthy.
colors:
  garden-sage: "#566D57"
  garden-sage-workspace: "#6E8C70"
  garden-sage-hover: "#5A7A5C"
  garden-sage-soft: "#DCE6DD"
  dusty-rose: "#D48BA0"
  dusty-rose-hover: "#C27889"
  dusty-rose-soft: "#F5DCE3"
  ink-navy: "#2C4A6B"
  warm-linen: "#F7F6F3"
  linen-panel: "#F4ECE6"
  card-white: "#FFFFFF"
  ink-text: "#2A3548"
  ink-dim: "#60697B"
  linen-border: "#E5DAD0"
  linen-border-bright: "#D6C5B8"
  clay-red: "#A24A46"
  harvest-amber: "#C8924C"
  midnight: "#14182A"
  midnight-panel: "#252A45"
  midnight-card: "#1C2138"
  moonlit-sage: "#8FAE92"
  moonlit-rose: "#E4A5B8"
  moonlit-text: "#ECE5DC"
typography:
  headline:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.3
  body:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 400
    lineHeight: 1.6
  input:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Geist Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.4
  code:
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1.55
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  xl: "12px"
  pill: "9999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  button-primary:
    backgroundColor: "{colors.garden-sage}"
    textColor: "#FFFFFF"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-outline:
    backgroundColor: "{colors.warm-linen}"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  button-secondary:
    backgroundColor: "{colors.dusty-rose}"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.lg}"
    padding: "0 10px"
    height: "32px"
  badge-secondary:
    backgroundColor: "{colors.dusty-rose}"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    height: "20px"
  input-default:
    backgroundColor: "transparent"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.lg}"
    padding: "4px 10px"
    height: "32px"
  card-default:
    backgroundColor: "{colors.card-white}"
    textColor: "{colors.ink-text}"
    rounded: "{rounded.xl}"
    padding: "16px"
---

# Design System: homelabhealth

## 1. Overview

**Creative North Star: "The Home Visit"**

Care that comes to you — personal, unhurried, on your turf rather than the institution's. The interface is the practitioner who sits down at your kitchen table: warm in manner (linen surfaces, garden sage, a touch of dusty rose), exact in substance (verbatim lab values, visible citations, audit trails). Every screen should lower the user's heart rate, not raise it. Density is deliberately low; the chat conversation at 18px is the loudest element on any screen, and the controls around it stay quiet.

The system explicitly rejects the four anti-references in PRODUCT.md: the **hospital portal / EHR** (no bureaucratic tab walls or institutional chrome), the **generic AI chat clone** (no dark-SaaS model-playground shell), **wellness-app pastel fluff** (warm never means cute — rigor is always visible), and the **homelab dashboard aesthetic** (the Docker plumbing stays backstage; this is never an ops console).

Both themes are first-class: Warm Linen by day, Midnight navy with moonlit sage by night, each held to WCAG AA.

**Key Characteristics:**
- Warm, flat, border-defined surfaces; depth from tinted panels, not shadows
- Large reading type (18px body floor) with compact, tactile controls
- Three color voices with strict jobs: sage acts, rose annotates, navy informs
- Provenance UI (citations, source panels) is decorated as first-class content
- Calm motion: 200ms fades and 4px rises, nothing choreographed

## 2. Colors

A soft domestic palette — Garden Sage carrying action, Dusty Rose carrying annotation, Ink Navy carrying structure — on Warm Linen surfaces.

### Primary
- **Garden Sage** (#566D57): the action color. Primary buttons, focus rings, active states, the sidebar's selected workspace. Deepened from the brand's display sage specifically to clear 4.5:1 with white text — the contrast fix is the canonical value, not a compromise.
- **Workspace Sage** (#6E8C70): the brighter display sage, reserved for non-text uses — workspace identity marks, chart series, the rare `--glow`.
- **Sage Whisper** (#DCE6DD): soft sage tint for selected/hover fills behind dark text.

### Secondary
- **Dusty Rose** (#D48BA0): annotation and identity. Citation badges, secondary chips, source highlights. Always paired with Ink Text (#2A3548) — white on rose fails contrast and is forbidden.
- **Rose Blush** (#F5DCE3): hover wash on rose-coded elements.

### Tertiary
- **Ink Navy** (#2C4A6B): structural headers and informational accents. Never a button fill.
- **Harvest Amber** (#C8924C): queued/pending states (e.g. queued chat messages) and the fourth chart voice.
- **Clay Red** (#A24A46): destructive and error only. Deepened for AA on cream; errors render as tinted fills (`destructive/10`) with Clay text, never solid red slabs.

### Neutral
- **Warm Linen** (#F7F6F3): the page. A true warm off-white, not a pastel.
- **Linen Panel** (#F4ECE6): sidebar, popovers, muted fills — one tone deeper than the page.
- **Card White** (#FFFFFF): cards and elevated content.
- **Ink Text** (#2A3548): all primary text — a navy-leaning ink, not pure black.
- **Ink Dim** (#60697B): secondary text. AA-verified on every linen surface; do not lighten.
- **Linen Border** (#E5DAD0) / **Linen Border Bright** (#D6C5B8): hairline dividers and input strokes.

### Dark theme
- **Midnight** (#14182A) page, **Midnight Panel** (#252A45), **Midnight Card** (#1C2138); text flips to **Moonlit Cream** (#ECE5DC); sage and rose lighten to **Moonlit Sage** (#8FAE92) and **Moonlit Rose** (#E4A5B8), with primary-foreground flipping dark. Same roles, same rules, same AA floor.

### Named Rules
**The Three Voices Rule.** Sage acts, rose annotates, navy informs. A color never borrows another's job: no rose buttons, no navy CTAs, no sage citation badges.

**The AA Floor Rule.** Every text/background pair clears WCAG AA (4.5:1 body, 3:1 large/UI). When a brand hue fails, deepen the token and document the fix in `globals.css` — the deepened value becomes canonical. Never restore a prettier hue at the cost of contrast.

## 3. Typography

**Display/Body Font:** Geist Variable (with ui-sans-serif, system-ui fallback)
**Mono Font:** JetBrains Mono Variable (with ui-monospace fallback)

**Character:** One warm geometric sans at generous sizes does all the talking; the mono appears only where data fidelity matters (code, lab values). Hierarchy comes from size and weight, never from a second display face.

### Hierarchy
- **Headline** (600, 24px / `--fs-heading`): page and section titles. Sentence case, often Ink Navy.
- **Body / Chat** (400, 18px / `--fs-chat`, 1.6): conversation prose, the loudest element on screen. Max measure ~70ch (`--chat-max-w: 900px`).
- **Input** (400, 20px / `--fs-input`): the chat composer — deliberately larger than body so the user's own words feel weighty.
- **Code** (400, 19px / `--fs-code`, JetBrains Mono): code blocks and verbatim values.
- **Label / Nav** (500, 15px / `--fs-nav`): sidebar items, control labels, metadata. The floor for any text.

### Named Rules
**The Reading Glasses Rule.** Prose never drops below 18px and labels never below 15px. If a layout needs smaller text to fit, the layout is wrong — users read lab results here, often anxious, often older.

**The One Voice Rule.** Geist is the only UI face. No decorative display fonts, no second sans.

## 4. Elevation

Flat by default, border-defined. Depth is conveyed by surface tone (Warm Linen page → Linen Panel → Card White) and 1px rings (`ring-foreground/10`), not by shadow. Dark mode adds a faint `shadow-black/30` on cards purely as a legibility aid against Midnight, and a soft sage `--glow` (`0 0 20px` at 15–25% alpha) exists as a rare emphasis accent — never ambient decoration.

### Shadow Vocabulary
- **Card ring** (`ring-1 ring-foreground/10`, dark: `/20` + `shadow-sm shadow-black/30`): the standard container edge.
- **Sage glow** (`0 0 20px rgba(110,140,112,0.15)`; dark `rgba(143,174,146,0.25)`): reserved for moments of focus or arrival; at most one element per screen.

### Named Rules
**The Border-Not-Shadow Rule.** If an element needs separation, reach for a border, ring, or one-step surface-tone change. A drop shadow is never the first tool, and stacked shadows are forbidden.

## 5. Components

Component character: **tactile and friendly** — and trending friendlier. Today's controls are compact and precise (32px buttons, 14px control text); the direction of travel is warmer and rounder: when touching a surface, prefer the larger size variant, full touch targets (≥40px on mobile), and the softer end of the radius scale. Never get warmer by getting less precise.

### Buttons
- **Shape:** gently rounded (10px / `--radius`), compact default height (32px, `h-8`)
- **Primary:** Garden Sage fill, white text, `hover:bg-primary/80`; pressed state nudges down 1px (`active:translate-y-px`) — the tactile signature
- **Hover / Focus:** all buttons take a 3px sage focus ring at 50% (`focus-visible:ring-3 ring-ring/50`); transitions use `transition-all` with `--ease-out` (cubic-bezier(0.23, 1, 0.32, 1))
- **Outline / Ghost:** linen-border stroke or borderless, washing to Linen Panel on hover
- **Secondary:** Dusty Rose fill with Ink Text (never white)
- **Destructive:** tinted (`bg-destructive/10` + Clay text), never a solid red slab

### Badges / Chips
- **Style:** full pill (`rounded-4xl`), 20px tall, 12px medium text
- **State:** rose for citations/identity, sage for active, tinted clay for errors, outline for neutral metadata

### Cards / Containers
- **Corner Style:** 12px (`rounded-xl`)
- **Background:** Card White (light) / Midnight Card (dark)
- **Shadow Strategy:** ring-only per the Border-Not-Shadow Rule; faint shadow in dark mode only
- **Internal Padding:** 16px (`p-4`), 12px for the `sm` size

### Inputs / Fields
- **Style:** transparent on light surfaces (`dark:bg-input/30`), 1px Linen Border Bright stroke, 10px radius, 32px height; the chat composer runs larger at 20px text
- **Focus:** border flips to sage + 3px sage ring at 50% — same vocabulary as buttons
- **Error:** Clay border + 3px clay ring at 20%, with plain-language message text in Clay

### Navigation (Sidebar)
- **Style:** 260px Linen Panel column; 15px medium labels; hover washes Sage Whisper; the active workspace marks with Garden Sage. Collapses behind the mobile header; chat composer pins to the visual viewport bottom on mobile.

### Chat Message (signature component)
- 18px prose on the bare page background — messages are NOT cards; user and assistant turns differentiate by alignment and typographic weight, not boxes. New messages enter with `message-in`: 200ms, 4px rise + fade on `--ease-out`, disabled under `prefers-reduced-motion`. Inline citation badges (rose) link each claim to its source; the sources panel (22rem) opens alongside rather than over the conversation.

## 6. Do's and Don'ts

### Do:
- **Do** keep the Three Voices honest: Garden Sage (#566D57) for actions, Dusty Rose (#D48BA0) for citations/annotation, Ink Navy (#2C4A6B) for structure.
- **Do** hold every pair to the AA Floor (4.5:1 body, 3:1 UI) in BOTH themes, and keep the deepened AA tokens canonical.
- **Do** use the 3px `ring-ring/50` focus treatment on every interactive element — one focus vocabulary everywhere.
- **Do** keep prose ≥18px, labels ≥15px, and chat measure ≤900px.
- **Do** give every animation a `prefers-reduced-motion` fallback; the global kill-switch in `globals.css` must keep working.
- **Do** make provenance visible: citations, source panels, and safeguard notices are styled as first-class content, in plain language.

### Don't:
- **Don't** drift toward the **hospital portal / EHR**: no dense tab bars, no institutional table chrome, no jargon-first error text.
- **Don't** build the **generic AI chat clone**: no dark-SaaS default theme, no message-bubble cards, no model-playground furniture in the chat surface.
- **Don't** slide into **wellness-app pastel fluff**: no decorative illustration sets, no rounded-everything cuteness, no softening of exact values.
- **Don't** let the **homelab dashboard aesthetic** leak frontstage: no Grafana-dark density, no raw container/ops vocabulary outside Settings.
- **Don't** put white text on Dusty Rose (2.62:1 — fails AA); rose always carries Ink Text.
- **Don't** use drop shadows for resting separation, colored side-stripe borders (`border-left` > 1px), gradient text, or glassmorphism — all prohibited.
- **Don't** use arbitrary z-index values; the semantic scale in `globals.css` (`--z-dropdown` 10 → `--z-tooltip` 70) is the only source.
- **Don't** lighten Ink Dim (#60697B) "for elegance" — it sits exactly at the AA floor on linen surfaces.
