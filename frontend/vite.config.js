import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

/** @param {string | undefined | null} raw */
function coerceAppMode(raw) {
  const v =
    raw == null || String(raw).trim() === ''
      ? 'booops'
      : String(raw).trim().toLowerCase()
  if (v === 'booops' || v === '808notes' || v === 'boolab') return v
  return 'booops'
}

/** @param {string} s */
function escapeHtmlAttr(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
}

/** Build-time OG / Twitter meta from `VITE_APP_MODE` (aligned with `src/api/branding.js` taglines). */
function socialMetaForEnv(env) {
  const appMode = coerceAppMode(env.VITE_APP_MODE)
  const byMode = {
    booops: {
      ogTitle: 'BooOps',
      description: 'LLM chat — personas, DAWs, memory.',
      canonical: (env.VITE_PUBLIC_BOOOPS_URL || '').trim().replace(/\/$/, ''),
      brandingPath: 'booops',
    },
    '808notes': {
      ogTitle: '808notes',
      description: 'Music notes, sources, and project context.',
      canonical: (env.VITE_PUBLIC_808NOTES_URL || '').trim().replace(/\/$/, ''),
      brandingPath: '808notes',
    },
    boolab: {
      ogTitle: 'BooLab',
      description: '// pick your lab bench.',
      canonical: (env.VITE_PUBLIC_BOOLAB_URL || '').trim().replace(/\/$/, ''),
      brandingPath: 'boolab',
    },
  }
  const m = byMode[appMode]
  const relImage = `/api/branding/${m.brandingPath}/asset/og-banner`
  const ogImage = m.canonical ? `${m.canonical}${relImage}` : relImage
  const ogUrl = m.canonical || ''
  const desc = escapeHtmlAttr(m.description)
  const title = escapeHtmlAttr(m.ogTitle)
  const image = escapeHtmlAttr(ogImage)
  const url = escapeHtmlAttr(ogUrl)

  const lines = [
    `<meta property="og:title" content="${title}" />`,
    `<meta property="og:description" content="${desc}" />`,
    `<meta property="og:type" content="website" />`,
    ...(ogUrl
      ? [`<meta property="og:url" content="${url}" />`]
      : []),
    `<meta property="og:image" content="${image}" />`,
    `<meta name="twitter:card" content="summary_large_image" />`,
    `<meta name="twitter:title" content="${title}" />`,
    `<meta name="twitter:description" content="${desc}" />`,
    `<meta name="twitter:image" content="${image}" />`,
  ]
  return `\n    ${lines.join('\n    ')}\n    `
}

function socialMetaHtmlPlugin(env) {
  return {
    name: 'boolab-social-meta-html',
    transformIndexHtml(html) {
      const block = socialMetaForEnv(env)
      if (html.includes('<!--vite:social-meta-->')) {
        return html.replace('<!--vite:social-meta-->', block.trimEnd())
      }
      return html.replace(/<\/head>/i, `${block.trimEnd()}\n  </head>`)
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '')
  const apiProxyTarget =
    (env.BOOLAB_VITE_API_PROXY || '').trim() || 'http://127.0.0.1:9300'

  return {
    plugins: [react(), socialMetaHtmlPlugin(env)],
    server: {
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
  }
})
