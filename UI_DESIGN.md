# boolab — UI Design Reference
Last updated: March 2026

## Design Principles
- Dark, high contrast, no wasted space
- Every UI element controllable from settings (colors, sizes, spacing)
- Mode-aware: BooOps feels like a terminal that grew up, 808notes feels like a focused workspace
- shadcn/ui for interactive primitives (Dialog, DropdownMenu, Tooltip, Popover, Select, Tabs)
- All colors via CSS variables — never hardcode hex in components
- Collapsible everything — respect focus

---

## Color Palettes

### BooOps (cyberpunk)
```css
:root[data-mode="booops"] {
  --accent:        #ff2d78;   /* neon pink */
  --accent-bright: #ff6eb0;
  --accent-dim:    #7c1a3d;
  --accent-2:      #00e5ff;   /* cyan */
  --accent-3:      #a855f7;   /* purple */
  --bg:            #050505;
  --bg-panel:      #0d0d0d;
  --bg-card:       #111111;
  --bg-hover:      #1a1a1a;
  --text:          #f0f0f0;
  --text-dim:      #888888;
  --text-muted:    #444444;
  --border:        #222222;
  --border-bright: #333333;
  --glow:          0 0 20px rgba(255, 45, 120, 0.3);
}
```

### 808notes (deep purple/black)
```css
:root[data-mode="808notes"] {
  --accent:        #7c3aed;   /* deep purple */
  --accent-bright: #a855f7;
  --accent-dim:    #3d1a7c;
  --accent-2:      #c084fc;   /* soft purple */
  --accent-3:      #e879f9;   /* magenta */
  --bg:            #080808;
  --bg-panel:      #0f0a1a;
  --bg-card:       #130d20;
  --bg-hover:      #1a1030;
  --text:          #f0f0f0;
  --text-dim:      #9d8fbb;
  --text-muted:    #4a3d6b;
  --border:        #1e1530;
  --border-bright: #2d2050;
  --glow:          0 0 20px rgba(124, 58, 237, 0.3);
}
```

### boolab landing
```css
:root[data-mode="boolab"] {
  --accent:        #6366f1;   /* indigo bridge color */
  --bg:            #030303;
  --bg-card:       #0d0d0d;
  --text:          #f0f0f0;
  --border:        #1a1a1a;
}
```

---

## Typography

### BooOps
- UI labels, headings: **Rajdhani** (Google Fonts)
- Chat/code: **Share Tech Mono** (Google Fonts)
- Body/messages: **Rajdhani** or **Inter**

### 808notes
- UI: **Rajdhani** or **Space Grotesk**
- Notes editor: **JetBrains Mono** (matches BourBites)
- Body: **Inter** or **DM Sans**

---

## Layout System

### BooOps Desktop
```
┌─────────────────────────────────────────────────────┐
│ [sidebar toggle]                    [mode indicator] │  ← header bar (minimal)
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│ SIDEBAR  │  CHAT AREA (full width when sidebar      │
│          │  collapsed)                              │
│ [banner] │                                          │
│ [newchat]│  [messages...]                           │
│ [search] │                                          │
│ [pinned] │                                          │
│ [recent] │  [input bar]                             │
│          │                                          │
│ [boolab] │                                          │
└──────────┴──────────────────────────────────────────┘
```

### 808notes Desktop (inside DAW)
```
┌──────────┬──────────────────────────┬───────────────┐
│          │                          │               │
│  CHATS   │  MAIN CHAT AREA          │  SOURCES      │
│  PANEL   │                          │  (top 2/3)    │
│          │  [messages...]           │               │
│ [banner] │                          ├───────────────┤
│ [search] │                          │  NOTES        │
│ [chats]  │  [input bar]             │  (bottom 1/3) │
│          │                          │  [collapsible]│
│ [boolab] │                          │               │
└──────────┴──────────────────────────┴───────────────┘
```

### Sidebar collapsed state
Both sidebars collapse to a thin rail (48px) showing only icons, or fully hidden with a toggle button visible in the header.

---

## Component Specs

### Chat Bubbles
```
User message:
  ┌─────────────────────────────────┐
  │                    [user text]  │ ← right-aligned
  │                   [user icon]   │ ← uploadable avatar
  └─────────────────────────────────┘

AI message:
  ┌─────────────────────────────────┐
  │ [ai icon]                       │ ← left-aligned
  │ [rendered markdown]             │
  │                                 │
  │ [copy] [save as note] [fork]    │ ← action row on hover
  └─────────────────────────────────┘
```

AI icon: per persona, defaults to mode mascot (westie for BooOps, 808 speaker for 808notes).
User icon: global upload, overridable per mode.

### Chat Input Bar
```
┌──────────────────────────────────────────────┐
│ [+]  Type a message...              [send ▶] │
└──────────────────────────────────────────────┘
  ↑
  + menu (popover):
  ├── Upload files
  ├── Web search [toggle]
  ├── Persona picker →
  ├── Add to DAW / Remove from DAW
  └── Change model →
```

### DAW Card (cards page)
```
┌─────────────────────────┐
│ [icon]                  │  ← uploadable, emoji or image
│                         │
│ DAW Name                │  ← bold
│ Description text here   │  ← dim, truncated
│                         │
│ [open]            [pin] │
└─────────────────────────┘
```
Card: customizable bg color, border color, glow. Hover: slight lift + glow intensifies.

### Source Item (808notes right panel)
```
┌─ [ ] ──────────────────────────────┐
│  📄 Week1_Readings.pdf             │
│  ████████████████░░░░ 80%          │ ← embedding progress (while processing)
│  12 chunks · PDF                   │ ← after complete
│                    [⋮ rename/del]  │
└─────────────────────────────────────┘
```
Checkbox selects/deselects source for RAG. Group header has collapse toggle.

### Note Item (808notes bottom panel)
```
┌─ [ ] ──────────────────────────────┐
│  📝 Week 1 Summary                 │
│  AI response · 2 days ago          │
│                [→source] [⋮ menu]  │
└─────────────────────────────────────┘
```

### Source Upload Modal (center overlay)
```
┌──────────────────────────────────────────┐
│  Add Sources                          [×] │
├──────────────────────────────────────────┤
│                                          │
│   ┌────────────────────────────────┐    │
│   │                                │    │
│   │   Drop files here or           │    │
│   │   [Browse Files]               │    │
│   │                                │    │
│   │   PDF · DOCX · TXT · MD        │    │
│   │   CSV · XLSX · HTML · URLs     │    │
│   └────────────────────────────────┘    │
│                                          │
│  [uploading files shown here with bars]  │
│                                          │
└──────────────────────────────────────────┘
```

### boolab Landing Page
```
┌──────────────────────────────────────────────────────┐
│                    boolab                            │
│                                                      │
│  ┌─────────────────────┐  ┌─────────────────────┐   │
│  │                     │  │                     │   │
│  │  [westie icon]      │  │  [808 icon]         │   │
│  │                     │  │                     │   │
│  │  BooOps             │  │  808notes           │   │
│  │  Your AI assistant  │  │  Your AI notebook   │   │
│  │                     │  │                     │   │
│  └─────────────────────┘  └─────────────────────┘   │
│                                                      │
└──────────────────────────────────────────────────────┘
```
Card bg, border, glow all customizable from boolab settings.

---

## Mobile Layouts

### BooOps Mobile
- Default view: latest chat or new chat screen
- Sidebar: slides in from left on hamburger tap
- Input bar: fixed bottom
- Same chat bubble layout, slightly more compact

### 808notes Mobile
- Default view: DAW cards landing page
- Inside a DAW: bottom nav bar
```
┌──────────────────────────────────────┐
│  [messages area]                     │
├──────────────────────────────────────┤
│  💬 Chats  |  ➕ New Chat  |  📚 Sources │
└──────────────────────────────────────┘
```
Each bottom nav item: emoji on top, label below (as specified).

---

## Settings Panel
Full-page settings with left nav sections. Not a modal.

```
Settings
├── boolab (global)
│   ├── Layout & Structure
│   ├── Landing Page
│   ├── API Keys
│   └── Default Model
├── BooOps
│   ├── Branding & Colors
│   ├── Typography
│   ├── Assets (banner, logo, favicon)
│   ├── Custom Instructions
│   └── Pruning Settings
├── 808notes
│   ├── Branding & Colors
│   ├── Typography
│   ├── Assets
│   ├── RAG Settings
│   ├── Custom Instructions
│   └── Pruning Settings
├── Personas
│   └── [manage personas]
└── Memory
    └── [view/edit memory entries]
```

---

## Animations & Effects
- Sidebar collapse: CSS transition 200ms ease
- Card hover: `transform: translateY(-2px)` + glow increase, 150ms
- Message appear: fade-in from bottom, 200ms
- Streaming text: no animation — just append characters
- Upload progress: smooth bar fill
- Modal open: scale from 0.95 + fade, 150ms
- Glow effects: `box-shadow` with accent color at 30% opacity
- No heavy animations — performance matters for chat
