import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

function coerceAppMode(raw) {
  const v =
    raw == null || String(raw).trim() === ''
      ? 'booops'
      : String(raw).trim().toLowerCase()
  if (v === 'booops' || v === '808notes' || v === 'boolab') return v
  return 'booops'
}

/** PWA / document title strings aligned with former `frontend/.env.<mode>` values. */
function displayNameFromAppMode(raw) {
  switch (coerceAppMode(raw)) {
    case 'booops':
      return 'BooOps'
    case 'boolab':
      return 'BooLab'
    case '808notes':
      return '808notes'
    default:
      return 'BooOps'
  }
}

function htmlDisplayNameFromAppModePlugin(env) {
  const displayName = displayNameFromAppMode(env.VITE_APP_MODE)
  return {
    name: 'html-display-name-from-app-mode',
    enforce: 'pre',
    transformIndexHtml(html) {
      return html
        .replaceAll('%VITE_HTML_TITLE%', displayName)
        .replaceAll('%VITE_PWA_SHORT_NAME%', displayName)
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const rootEnv = fs.existsSync(path.join(repoRoot, '.env'))
    ? loadEnv(mode, repoRoot, '')
    : {}
  const feEnv = loadEnv(mode, __dirname, '')
  const env = { ...rootEnv, ...feEnv }
  const appModeFromShell = process.env.VITE_APP_MODE
  if (appModeFromShell != null && String(appModeFromShell).trim() !== '') {
    env.VITE_APP_MODE = appModeFromShell
  }
  const apiProxyTarget =
    (env.BOOLAB_VITE_API_PROXY || '').trim() || 'http://127.0.0.1:9300'

  return {
    envDir: __dirname,
    plugins: [htmlDisplayNameFromAppModePlugin(env), react()],
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
