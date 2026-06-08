import tailwindcssAnimate from 'tailwindcss-animate'

/**
 * Theme color tokens are CSS custom properties holding full color values
 * (hex), defined in the single source of truth: src/styles/globals.css
 * (:root + .dark). Tailwind cannot inject an alpha channel into a bare
 * `var(--x)`, so opacity-modified utilities (`bg-primary/10`, `ring-ring/50`,
 * `border-accent/30`, …) silently emitted NO CSS at all.
 *
 * `alpha()` returns a color function so that:
 *   • resting utilities stay byte-identical to before — `var(--x)` — preserving
 *     today's effective appearance exactly, and
 *   • opacity-modified utilities resolve to a real color via `color-mix`
 *     (a technique already used throughout the app's CSS/JSX).
 *
 * We use `color-mix` rather than the shadcn `rgb(var(--x) / <alpha-value>)`
 * pattern because the tokens hold full hex colors, not space-separated channel
 * triplets, and many raw CSS/JSX consumers read these vars directly as full
 * colors (e.g. `color-mix(in srgb, var(--accent) 45%, transparent)`). Switching
 * to channels would break every such consumer; this keeps them all working.
 */
function alpha(varName) {
  return ({ opacityValue }) => {
    if (opacityValue === undefined || String(opacityValue).startsWith('var(')) {
      return `var(${varName})`
    }
    return `color-mix(in srgb, var(${varName}) calc(${opacityValue} * 100%), transparent)`
  }
}

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        // Bundled via @fontsource-variable imports in src/index.css.
        sans: ['Geist Variable', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        heading: ['Geist Variable', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono Variable', 'ui-monospace', 'monospace'],
      },
      colors: {
        border: alpha('--border'),
        input: alpha('--input'),
        ring: alpha('--ring'),
        background: alpha('--background'),
        foreground: alpha('--foreground'),
        primary: {
          DEFAULT: alpha('--primary'),
          foreground: alpha('--primary-foreground'),
        },
        secondary: {
          DEFAULT: alpha('--secondary'),
          foreground: alpha('--secondary-foreground'),
        },
        destructive: {
          DEFAULT: alpha('--destructive'),
          foreground: alpha('--destructive-foreground'),
        },
        muted: {
          DEFAULT: alpha('--muted'),
          foreground: alpha('--muted-foreground'),
        },
        accent: {
          DEFAULT: alpha('--accent'),
          foreground: alpha('--accent-foreground'),
        },
        'accent-hover': alpha('--accent-hover'),
        'accent-soft': alpha('--accent-soft'),
        'secondary-hover': alpha('--secondary-hover'),
        'secondary-soft': alpha('--secondary-soft'),
        tertiary: alpha('--tertiary'),
        popover: {
          DEFAULT: alpha('--popover'),
          foreground: alpha('--popover-foreground'),
        },
        card: {
          DEFAULT: alpha('--card'),
          foreground: alpha('--card-foreground'),
        },
        sidebar: {
          DEFAULT: alpha('--sidebar'),
          foreground: alpha('--sidebar-foreground'),
          primary: alpha('--sidebar-primary'),
          'primary-foreground': alpha('--sidebar-primary-foreground'),
          accent: alpha('--sidebar-accent'),
          'accent-foreground': alpha('--sidebar-accent-foreground'),
          border: alpha('--sidebar-border'),
          ring: alpha('--sidebar-ring'),
        },
        chart: {
          1: alpha('--chart-1'),
          2: alpha('--chart-2'),
          3: alpha('--chart-3'),
          4: alpha('--chart-4'),
          5: alpha('--chart-5'),
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
    },
  },
  plugins: [tailwindcssAnimate],
}
