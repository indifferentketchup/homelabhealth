import { apiFetch } from './index.js'

/** DubDrive proxy: list directory (auth cookie/header via `apiFetch`). */
export async function dubdriveLs(path) {
  const q = new URLSearchParams()
  if (path != null && path !== '') q.set('path', path)
  return apiFetch(`/api/dubdrive/ls?${q}`)
}

/** DubDrive proxy: read file body (JSON or text depending on upstream). */
export async function dubdriveRead(path) {
  const q = new URLSearchParams({ path })
  return apiFetch(`/api/dubdrive/read?${q}`)
}
