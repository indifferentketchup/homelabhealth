import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(__dirname, '..')

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const rootEnv = fs.existsSync(path.join(repoRoot, '.env'))
    ? loadEnv(mode, repoRoot, '')
    : {}
  const feEnv = loadEnv(mode, __dirname, '')
  const env = { ...rootEnv, ...feEnv }
  const apiProxyTarget =
    (env.HLH_VITE_API_PROXY || '').trim() || 'http://127.0.0.1:9600'

  return {
    envDir: __dirname,
    plugins: [
      react(),
    ],
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
