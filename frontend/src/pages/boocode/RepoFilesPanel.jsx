import { useMemo, useState, useCallback, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Virtuoso } from 'react-virtuoso'
import Fuse from 'fuse.js'
import { ChevronRight, ChevronDown, File as FileIcon, RefreshCw } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'

import { listRepoTree } from '@/api/boocode.js'
import { cn } from '@/lib/utils.js'

function buildTree(files) {
  const root = { name: '', path: '', isDir: true, children: new Map() }
  for (const f of files) {
    const parts = f.path.split('/')
    let node = root
    let acc = ''
    for (let i = 0; i < parts.length; i++) {
      const name = parts[i]
      acc = acc ? `${acc}/${name}` : name
      if (i === parts.length - 1) {
        node.children.set(name, { name, path: acc, isDir: false, file: f })
      } else {
        let next = node.children.get(name)
        if (!next) {
          next = { name, path: acc, isDir: true, children: new Map() }
          node.children.set(name, next)
        }
        node = next
      }
    }
  }
  return root
}

function flatten(node, depth, expanded, out) {
  if (depth >= 0) out.push({ ...node, depth })
  if (!node.isDir) return
  if (depth >= 0 && !expanded.has(node.path)) return
  const children = Array.from(node.children.values())
  children.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1
    return a.name.localeCompare(b.name)
  })
  for (const c of children) flatten(c, depth + 1, expanded, out)
}

const RECENT_KEY = (dawId) => `bc-recent-files:${dawId}`
const MAX_RECENT = 5

export function RepoFilesPanel({ dawId }) {
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState(() => new Set())
  const [activeIdx, setActiveIdx] = useState(0)
  const inputRef = useRef(null)

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['repo-tree', dawId],
    queryFn: () => listRepoTree(dawId),
    staleTime: 60_000,
    enabled: Boolean(dawId),
  })
  const files = Array.isArray(data?.files) ? data.files : []

  const tree = useMemo(() => buildTree(files), [files])
  const flatRows = useMemo(() => {
    const out = []
    flatten(tree, -1, expanded, out)
    return out
  }, [tree, expanded])

  const fuse = useMemo(
    () => new Fuse(files, { keys: ['path'], threshold: 0.4, ignoreLocation: true }),
    [files],
  )

  const filteredRows = useMemo(() => {
    const q = filter.trim()
    if (!q) return flatRows
    return fuse.search(q).slice(0, 200).map((h) => ({
      isDir: false,
      file: h.item,
      depth: 0,
      path: h.item.path,
      name: h.item.path.split('/').pop() || h.item.path,
    }))
  }, [filter, flatRows, fuse])

  useEffect(() => { setActiveIdx(0) }, [filter])

  const openFile = useCallback((row) => {
    if (!row || row.isDir) return
    const next = new URLSearchParams(params)
    next.set('file', row.path)
    next.delete('line')
    setParams(next, { replace: true })
    try {
      const key = RECENT_KEY(dawId)
      const raw = localStorage.getItem(key)
      const arr = raw ? JSON.parse(raw) : []
      const uniq = [row.path, ...arr.filter((p) => p !== row.path)].slice(0, MAX_RECENT)
      localStorage.setItem(key, JSON.stringify(uniq))
    } catch { /* ignore */ }
  }, [params, setParams, dawId])

  const toggleDir = (p) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p); else next.add(p)
      return next
    })
  }

  const onKeyDown = (e) => {
    if (e.key === '/') {
      e.preventDefault()
      inputRef.current?.focus()
      return
    }
    if (document.activeElement === inputRef.current &&
        e.key !== 'ArrowDown' && e.key !== 'ArrowUp' &&
        e.key !== 'Enter' && e.key !== 'Escape') {
      return
    }
    if (e.key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIdx((i) => Math.min(i + 1, Math.max(filteredRows.length - 1, 0)))
    } else if (e.key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === 'Enter') {
      const row = filteredRows[activeIdx]
      if (row?.isDir) { toggleDir(row.path); return }
      openFile(row)
    } else if (e.key === 'a') {
      const row = filteredRows[activeIdx]
      if (row && !row.isDir) {
        window.dispatchEvent(new CustomEvent('boocode:attach-file', {
          detail: { dawId, path: row.path, language: row.file?.language },
        }))
      }
    } else if (e.key === 'Escape') {
      inputRef.current?.blur()
    }
  }

  const row = (idx) => {
    const r = filteredRows[idx]
    if (!r) return null
    const active = idx === activeIdx
    const pad = Math.max(r.depth, 0) * 12
    return (
      <div
        className={cn(
          'flex cursor-pointer select-none items-center gap-1 font-mono text-xs',
          active && 'bg-accent',
        )}
        style={{ paddingLeft: 8 + pad }}
        draggable={!r.isDir}
        onDragStart={(e) => {
          if (r.isDir) return
          e.dataTransfer.setData('application/x-boocode-file',
            JSON.stringify({ dawId, path: r.path, language: r.file?.language }))
          e.dataTransfer.effectAllowed = 'copy'
        }}
        onClick={() => r.isDir ? toggleDir(r.path) : openFile(r)}
        onMouseEnter={() => setActiveIdx(idx)}
      >
        {r.isDir ? (
          expanded.has(r.path) ? <ChevronDown className="size-3 shrink-0 opacity-70" />
                               : <ChevronRight className="size-3 shrink-0 opacity-70" />
        ) : (
          <FileIcon className="size-3 shrink-0 opacity-70" />
        )}
        <span className="truncate">{r.name}</span>
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col" onKeyDown={onKeyDown} tabIndex={0}>
      <div className="flex items-center gap-2 border-b px-2 py-1"
           style={{ borderColor: 'var(--border)' }}>
        <span style={{ color: 'var(--orange)' }}>&gt;</span>
        <input
          ref={inputRef}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter files…"
          className="w-full bg-transparent font-mono text-xs outline-none"
        />
        <button type="button" onClick={() => refetch()}
                className="rounded-md border p-1" style={{ borderColor: 'var(--border)' }}
                aria-label="Refresh tree">
          <RefreshCw className="size-3" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        {isLoading ? (
          <div className="p-3 text-xs" style={{ color: 'var(--text-dim)' }}>loading tree…</div>
        ) : filteredRows.length === 0 ? (
          <div className="p-3 text-xs" style={{ color: 'var(--text-dim)' }}>
            {files.length === 0 ? 'No files ingested. Run `sync now`.' : 'No matches.'}
          </div>
        ) : (
          <Virtuoso
            totalCount={filteredRows.length}
            itemContent={row}
            style={{ height: '100%' }}
          />
        )}
      </div>
      <div className="border-t px-2 py-1 text-[0.625rem]"
           style={{ borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
        <span className="bc-key-hint">/</span> filter ·
        <span className="bc-key-hint ml-1">j/k</span> move ·
        <span className="bc-key-hint ml-1">⏎</span> open ·
        <span className="bc-key-hint ml-1">a</span> attach
      </div>
    </div>
  )
}
