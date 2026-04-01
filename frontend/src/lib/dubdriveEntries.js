/** DubDrive home root for HomeLab repos (boolab file picker + browser). */
export const DUBDRIVE_HOMELAB_ROOT = '/data/files/samkintop/HomeLabRepos/'

function ensureTrailingSlashDir(p) {
  if (!p) return '/'
  return p.endsWith('/') ? p : `${p}/`
}

function rowToEntry(row, parentPath) {
  const base = parentPath.endsWith('/') ? parentPath : `${parentPath}/`
  if (typeof row === 'string') {
    const s = row.trim()
    if (!s) return null
    const path = s.startsWith('/') ? s : `${base}${s.replace(/^\/*/, '')}`
    const name = path.replace(/\/+$/, '').split('/').pop() || s
    const isDir = /\/$/.test(s)
    return { name, path: isDir ? ensureTrailingSlashDir(path) : path, isDir }
  }
  if (!row || typeof row !== 'object') return null
  const name =
    row.name ??
    row.filename ??
    (typeof row.path === 'string' ? row.path.replace(/\/+$/, '').split('/').pop() : null) ??
    '?'
  let path = row.path ?? row.full_path ?? row.rel_path
  if (typeof path !== 'string' || !path) {
    path = `${base.replace(/\/+$/, '')}/${String(name).replace(/^\/*/, '')}`
  }
  let isDir = row.is_dir ?? row.isDir ?? row.directory
  if (isDir == null) {
    isDir = row.type === 'dir' || row.type === 'directory'
  }
  isDir = Boolean(isDir)
  return {
    name: String(name),
    path: isDir ? ensureTrailingSlashDir(path) : path,
    isDir,
  }
}

/**
 * Normalize DubDrive `/api/ls` JSON into sorted `{ name, path, isDir }[]`.
 * @param {unknown} data
 * @param {string} parentPath
 */
export function normalizeDubdriveLsPayload(data, parentPath) {
  let rows = []
  if (Array.isArray(data)) rows = data
  else if (data && typeof data === 'object') {
    for (const key of ['entries', 'items', 'files', 'children', 'results']) {
      if (Array.isArray(/** @type {any} */ (data)[key])) {
        rows = /** @type {any} */ (data)[key]
        break
      }
    }
  }
  const out = []
  for (const row of rows) {
    const entry = rowToEntry(row, parentPath)
    if (entry) out.push(entry)
  }
  out.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
    return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  })
  return out
}

/** Parent directory with trailing slash, or '/' */
export function parentDirectoryPath(path) {
  const s = path.replace(/\/+$/, '')
  if (!s) return '/'
  const i = s.lastIndexOf('/')
  if (i <= 0) return '/'
  return `${s.slice(0, i + 1)}`
}

/**
 * If the caret is inside an `@mention` token ( `@` at line/word start, no whitespace after `@` in the token).
 * @returns {{ start: number, query: string } | null}
 */
export function getActiveMention(text, caret) {
  if (caret == null || caret < 0) return null
  const before = text.slice(0, caret)
  const at = before.lastIndexOf('@')
  if (at < 0) return null
  if (at > 0 && !/\s/.test(text[at - 1])) return null
  const after = before.slice(at + 1)
  if (/[\s\n]/.test(after)) return null
  return { start: at, query: after }
}

/** Subsequence fuzzy match (lowercase). */
export function fuzzyMatchFilename(name, query) {
  const n = name.toLowerCase()
  const q = (query || '').toLowerCase()
  if (!q) return true
  let j = 0
  for (let i = 0; i < n.length && j < q.length; i += 1) {
    if (n[i] === q[j]) j += 1
  }
  return j === q.length
}

/**
 * @param {string} dirPath
 * @param {(p: string) => Promise<unknown>} ls
 * @returns {Promise<Array<{ name: string, path: string, isDir: boolean }>>}
 */
export async function collectAllFilesUnder(dirPath, ls) {
  const data = await ls(dirPath)
  const entries = normalizeDubdriveLsPayload(data, dirPath)
  const files = []
  for (const e of entries) {
    if (e.isDir) {
      const sub = await collectAllFilesUnder(e.path, ls)
      files.push(...sub)
    } else {
      files.push(e)
    }
  }
  return files
}
