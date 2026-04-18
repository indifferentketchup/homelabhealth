import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { FolderOpen, Plus, Search, SendHorizontal, Square, Upload, X, BookOpen } from 'lucide-react'

import { dubdriveLs, dubdriveRead } from '@/api/dubdrive.js'
import { toggleWebSearch } from '@/api/chats.js'
import { listSkills, searchSkills, fetchSkillFromUrl } from '@/api/skills.js'
import { Button } from '@/components/ui/button'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

import { FileBrowserPanel } from './FileBrowserPanel.jsx'
import { PersonaGlyph } from './PersonaGlyph.jsx'

export function ChatInput({
  inputRef,
  value,
  onChange,
  onSend,
  disabled,
  streaming,
  onStop,
  activeChatId,
  chatMaxW,
  hidePersonaInMenu = false,
  dawSyncFolder,
}) {
  const taRef = useRef(null)
  const uploadInputRef = useRef(null)
  const plusWrapRef = useRef(null)
  const plusBtnRef = useRef(null)
  const plusMenuRef = useRef(null)
  const [menuPos, setMenuPos] = useState({ bottom: 0, left: 0 })
  const [plusOpen, setPlusOpen] = useState(false)
  const [toastMsg, setToastMsg] = useState(null)

  const [attachedFiles, setAttachedFiles] = useState([])
  const [atQuery, setAtQuery] = useState(null)
  const [atResults, setAtResults] = useState([])
  const [atLoading, setAtLoading] = useState(false)
  const [atIndex, setAtIndex] = useState(0)
  const [fileBrowserOpen, setFileBrowserOpen] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)
  const [skillsModalOpen, setSkillsModalOpen] = useState(false)
  const [sessionSkillIds, setSessionSkillIds] = useState([])
  const [skillsModalData, setSkillsModalData] = useState({ sessionSkills: [], dawSkills: [], allSkills: [] })
  const [skillsLoading, setSkillsLoading] = useState(false)
  const [skillSearchQuery, setSkillSearchQuery] = useState(null)
  const [skillSearchResults, setSkillSearchResults] = useState([])
  const [skillSearchLoading, setSkillSearchLoading] = useState(false)

  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const setWebSearchEnabled = useAppStore((s) => s.setWebSearchEnabled)
  const personaDisplayName = useAppStore((s) => s.personaDisplayName)
  const personaIconUrl = useAppStore((s) => s.personaIconUrl)
  const personaEmoji = useAppStore((s) => s.personaEmoji)

  const q = (atQuery || '').toLowerCase()
  const filtered =
    atQuery !== null
      ? atResults.filter((item) => item.name.toLowerCase().includes(q)).slice(0, 8)
      : []

  useEffect(() => {
    if (!toastMsg) return
    const t = window.setTimeout(() => setToastMsg(null), 2200)
    return () => window.clearTimeout(t)
  }, [toastMsg])

  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    const maxPx = window.innerHeight * 0.4
    el.style.height = `${Math.min(el.scrollHeight, maxPx)}px`
  }, [value])

  useEffect(() => {
    if (!plusOpen) return
    function onMouseDown(e) {
      if (
        plusWrapRef.current &&
        !plusWrapRef.current.contains(e.target) &&
        plusMenuRef.current &&
        !plusMenuRef.current.contains(e.target)
      ) {
        setPlusOpen(false)
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [plusOpen])

  useEffect(() => {
    if (!plusOpen) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setPlusOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [plusOpen])

  useEffect(() => {
    if (!skillsModalOpen) return
    function onKeyDown(e) {
      if (e.key === 'Escape') setSkillsModalOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [skillsModalOpen])

  async function applyWebSearch(next) {
    const prev = webSearchEnabled
    setWebSearchEnabled(next)
    if (activeChatId) {
      try {
        const res = await toggleWebSearch(activeChatId, next)
        if (res?.web_search_enabled != null) setWebSearchEnabled(Boolean(res.web_search_enabled))
      } catch {
        setWebSearchEnabled(prev)
      }
    }
  }

  function handleSend() {
    if (streaming || disabled) return
    if (attachedFiles.length > 0) {
      const blocks = attachedFiles
        .map((f) => `**\`${f.filename}\`**\n\`\`\`\n${f.content}\n\`\`\``)
        .join('\n\n')
      const composed = blocks + (value.trim() ? '\n\n' + value.trim() : '')
      if (!composed.trim()) return
      setAttachedFiles([])
      onChange('')
      onSend(composed, { session_skill_ids: sessionSkillIds })
    } else {
      if (!value.trim()) return
      onSend(value, { session_skill_ids: sessionSkillIds })
    }
  }

  async function selectAtFile(item) {
    setAtQuery(null)
    setAtResults([])
    const newVal = value.replace(/(?:^|\s)@\S*$/, (m) => (m.startsWith('@') ? '' : m[0]))
    onChange(newVal.trimEnd())
    try {
      const content = await dubdriveRead(item.path)
      setAttachedFiles((prev) => {
        if (prev.find((f) => f.path === item.path)) return prev
        return [...prev, { filename: item.name, path: item.path, content }]
      })
    } catch {
      /* silently fail — file just won't be attached */
    }
  }

  function onKeyDownTa(e) {
    if (atQuery !== null) {
      const flen = filtered.length
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setAtIndex((i) => Math.min(i + 1, Math.max(0, flen - 1)))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setAtIndex((i) => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter') {
        e.preventDefault()
        if (filtered[atIndex]) void selectAtFile(filtered[atIndex])
        return
      }
      if (e.key === 'Escape') {
        setAtQuery(null)
        setAtResults([])
        return
      }
    }
    if (skillSearchQuery !== null) {
      if (e.key === 'Escape') {
        setSkillSearchQuery(null)
        setSkillSearchResults([])
        return
      }
      if (e.key === 'Enter' && !e.shiftKey && skillSearchResults.length > 0) {
        e.preventDefault()
        // Auto-save first result to library
        const firstResult = skillSearchResults[0]
        const skillPath = firstResult.skill_path || `${firstResult.title.replace(/\s+/g, '-').toLowerCase()}`
        fetchSkillFromUrl(`skills.sh/${skillPath}`)
          .then(() => {
            setSkillSearchQuery(null)
            setSkillSearchResults([])
            const newVal = value.replace(/\/skill\s+.+$/, '').trim()
            onChange(newVal)
          })
          .catch((err) => console.error('Failed to fetch skill:', err))
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const canSend =
    (Boolean(value.trim()) || attachedFiles.length > 0) && !streaming && !disabled

  const recalcMenuPos = useCallback(() => {
    const btn = plusBtnRef.current
    if (!btn) return
    const r = btn.getBoundingClientRect()
    setMenuPos({ bottom: window.innerHeight - r.top + 8, left: r.left })
  }, [])

  useEffect(() => {
    if (!plusOpen) return
    const onViewportChange = () => recalcMenuPos()
    const vv = window.visualViewport
    window.addEventListener('resize', onViewportChange)
    window.addEventListener('scroll', onViewportChange, true)
    vv?.addEventListener('resize', onViewportChange)
    vv?.addEventListener('scroll', onViewportChange)
    return () => {
      window.removeEventListener('resize', onViewportChange)
      window.removeEventListener('scroll', onViewportChange, true)
      vv?.removeEventListener('resize', onViewportChange)
      vv?.removeEventListener('scroll', onViewportChange)
    }
  }, [plusOpen, recalcMenuPos])

  function openPlus() {
    recalcMenuPos()
    setPlusOpen((o) => !o)
  }

  return (
    <>
      {toastMsg && (
        <div
          role="status"
          className="fixed bottom-20 left-1/2 z-[200] max-w-sm -translate-x-1/2 rounded-md border border-border bg-popover px-4 py-2 text-center text-sm text-popover-foreground shadow-md"
        >
          {toastMsg}
        </div>
      )}
      <div
        className="relative mx-auto w-full max-h-[40dvh] min-h-0 flex-shrink-0 flex flex-col overflow-hidden rounded-2xl border border-border bg-card px-4 pb-1.5 pt-3 transition-colors focus-within:border-ring/60 focus-within:ring-2 focus-within:ring-ring/30"
        style={{ maxWidth: chatMaxW ?? '100%' }}
        onDragOver={(e) => {
          e.preventDefault()
          setIsDragOver(true)
        }}
        onDragLeave={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget)) setIsDragOver(false)
        }}
        onDrop={async (e) => {
          e.preventDefault()
          setIsDragOver(false)
          const files = Array.from(e.dataTransfer.files)
          for (const file of files) {
            const text = await file.text().catch(() => null)
            if (text === null) continue
            setAttachedFiles((prev) => {
              if (prev.find((f) => f.filename === file.name)) return prev
              return [...prev, { filename: file.name, path: file.name, content: text }]
            })
          }
        }}
      >
        {isDragOver && (
          <div className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded-2xl border-2 border-dashed border-primary bg-primary/10">
            <span className="text-sm font-medium text-primary">Drop files to attach</span>
          </div>
        )}
        <div className="relative min-h-0">
          {/* Skill search results popup */}
          {skillSearchQuery !== null && (
            <div className="absolute bottom-full left-0 z-50 mb-2 w-96 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
              {skillSearchLoading ? (
                <div className="px-3 py-2 text-sm text-muted-foreground">Searching...</div>
              ) : skillSearchResults.length === 0 ? (
                <div className="px-3 py-2 text-sm text-muted-foreground">No skills found</div>
              ) : (
                <div className="max-h-96 overflow-y-auto">
                  {skillSearchResults.map((result, idx) => {
                    const skillPath = result.skill_path || `${result.title.replace(/\s+/g, '-').toLowerCase()}`
                    return (
                      <div key={idx} className="border-b border-border last:border-0">
                        <div className="p-3">
                          <div className="font-medium text-sm mb-1">{result.title}</div>
                          <div className="text-xs text-muted-foreground truncate mb-1">{result.url}</div>
                          <div className="text-xs text-muted-foreground line-clamp-2 mb-2">{result.snippet}</div>
                          <div className="flex flex-wrap gap-1">
                            <button
                              type="button"
                              className="flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs text-primary-foreground hover:bg-primary/90"
                              onClick={async () => {
                                try {
                                  await fetchSkillFromUrl(`skills.sh/${skillPath}`)
                                  setSkillSearchQuery(null)
                                  setSkillSearchResults([])
                                  // Clear the slash command from input
                                  const newVal = value.replace(/\/skill\s+.+$/, '').trim()
                                  onChange(newVal)
                                } catch (err) {
                                  console.error('Failed to fetch skill:', err)
                                }
                              }}
                            >
                              <Plus className="w-3 h-3" />
                              Save to Library
                            </button>
                            <button
                              type="button"
                              className="flex items-center gap-1 rounded-md bg-secondary px-2 py-1 text-xs text-secondary-foreground hover:bg-secondary/90"
                              onClick={() => {
                                // For now, just clear the command - actual implementation would require fetching first
                                const newVal = value.replace(/\/skill\s+.+$/, '').trim()
                                onChange(newVal)
                                setSkillSearchQuery(null)
                                setSkillSearchResults([])
                                setToastMsg('Skill added to this chat (fetch required first)')
                              }}
                            >
                              Add to chat
                            </button>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
          {/* @ mention popup */}
          {atQuery !== null && (
            <div className="absolute bottom-full left-0 z-50 mb-2 w-72 overflow-hidden rounded-lg border border-border bg-popover shadow-lg">
              {atLoading && <div className="px-3 py-2 text-sm text-muted-foreground">Loading…</div>}
              {!atLoading && filtered.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground">No files found</div>
              )}
              {!atLoading &&
                filtered.map((item, i) => (
                  <button
                    key={item.path}
                    type="button"
                    className={cn(
                      'flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors hover:bg-accent',
                      i === atIndex && 'bg-accent text-accent-foreground',
                    )}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      void selectAtFile(item)
                    }}
                  >
                    <span className="truncate">{item.name}</span>
                    <span className="ml-auto max-w-[120px] truncate text-xs text-muted-foreground">
                      {item.path}
                    </span>
                  </button>
                ))}
            </div>
          )}
          <textarea
            ref={(el) => {
              taRef.current = el
              if (inputRef != null) inputRef.current = el
            }}
            value={value}
            onChange={(e) => {
              const val = e.target.value
              onChange(val)
              // Handle @ mentions for file attachments
              const atMatch = val.match(/(?:^|\s)@(\S*)$/)
              if (atMatch) {
                const qq = atMatch[1]
                setAtQuery(qq)
                setAtIndex(0)
                setAtLoading(true)
                setSkillSearchQuery(null)
                setSkillSearchResults([])
                dubdriveLs((dawSyncFolder && String(dawSyncFolder).trim()) || '/HomeLabRepos')
                  .then((data) => {
                    const files = (data?.items || []).filter(
                      (i) => (i?.type || '').toLowerCase() === 'file',
                    )
                    setAtResults(files)
                    setAtLoading(false)
                  })
                  .catch(() => {
                    setAtResults([])
                    setAtLoading(false)
                  })
              } else {
                setAtQuery(null)
                setAtResults([])
                // Handle /skill slash command
                const skillMatch = val.match(/(?:^|\s)\/skill\s+(.+)$/)
                if (skillMatch && skillMatch[1].trim().length > 0) {
                  const query = skillMatch[1].trim()
                  setSkillSearchQuery(query)
                  if (!skillSearchLoading) {
                    setSkillSearchLoading(true)
                    searchSkills(query)
                      .then((data) => {
                        setSkillSearchResults(data.results || [])
                        setSkillSearchLoading(false)
                      })
                      .catch(() => {
                        setSkillSearchResults([])
                        setSkillSearchLoading(false)
                      })
                  }
                } else {
                  setSkillSearchQuery(null)
                  setSkillSearchResults([])
                }
              }
            }}
            onKeyDown={onKeyDownTa}
            placeholder="Message…"
            disabled={disabled || streaming}
            rows={1}
            className="fs-input max-h-[calc(40dvh-2.75rem)] min-h-12 w-full resize-none overflow-y-auto border-0 bg-transparent text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-0 focus-visible:ring-offset-0"
          />
        </div>
        {attachedFiles.length > 0 && (
          <div className="flex flex-wrap gap-1.5 pb-1.5 pt-0.5">
            {attachedFiles.map((f) => (
              <span
                key={f.path}
                className="flex items-center gap-1 rounded-md border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground"
              >
                <span className="max-w-[180px] truncate">{f.filename}</span>
                <button
                  type="button"
                  aria-label={`Remove ${f.filename}`}
                  className="ml-0.5 inline-flex size-4 items-center justify-center rounded text-muted-foreground outline-none transition-colors hover:bg-destructive/15 hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
                  onClick={() => setAttachedFiles((prev) => prev.filter((x) => x.path !== f.path))}
                >
                  <X className="size-3" aria-hidden />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex shrink-0 items-center justify-between">
          <div ref={plusWrapRef} className="relative shrink-0">
            <span ref={plusBtnRef} className="inline-flex shrink-0">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0"
                aria-label="More actions"
                aria-expanded={plusOpen}
                aria-haspopup="menu"
                onClick={openPlus}
              >
                <Plus className="size-4" />
              </Button>
            </span>
          </div>

          {streaming ? (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0 animate-pulse"
              title="Stop generating"
              onClick={onStop}
              aria-label="Stop"
            >
              <Square className="size-4" />
            </Button>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="shrink-0"
              onClick={handleSend}
              disabled={disabled || !canSend}
              aria-label="Send"
            >
              <SendHorizontal className="size-4" />
            </Button>
          )}
        </div>
      </div>
      {plusOpen &&
        createPortal(
          <div
            ref={plusMenuRef}
            className="fixed z-[9999] w-64 min-w-[16rem] rounded-lg border border-border bg-popover p-2 text-popover-foreground shadow-xl outline-none"
            style={{
              bottom: menuPos.bottom,
              left: menuPos.left,
            }}
            role="menu"
            aria-label="More actions"
          >
            <div className="flex flex-col gap-1">
              <button
                type="button"
                role="menuitem"
                className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  setPlusOpen(false)
                  uploadInputRef.current?.click()
                }}
              >
                <Upload className="size-4 shrink-0 opacity-70" />
                Upload file
              </button>
               <button
                type="button"
                role="menuitem"
                className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  setFileBrowserOpen(true)
                  setPlusOpen(false)
                }}
              >
                <FolderOpen className="size-4 text-muted-foreground" />
                Browse files
              </button>
              <button
                type="button"
                role="menuitem"
                className="flex h-9 w-full items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                onClick={() => {
                  setSkillsModalOpen(true)
                  setPlusOpen(false)
                }}
              >
                <BookOpen className="size-4 text-muted-foreground" />
                Skills
              </button>
              <div
                className={cn(
                  'flex items-center justify-between gap-2 rounded-md px-2 py-1.5',
                  webSearchEnabled && 'bg-accent text-accent-foreground',
                )}
              >
                <span className="flex items-center gap-2 text-sm">
                  <Search
                    className={cn(
                      'size-4',
                      webSearchEnabled ? 'text-accent-foreground' : 'text-muted-foreground',
                    )}
                  />
                  Web search
                </span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={webSearchEnabled}
                  onClick={() => applyWebSearch(!webSearchEnabled)}
                  className={cn(
                    'relative inline-flex h-6 w-10 shrink-0 rounded-full border border-border transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
                    webSearchEnabled ? 'bg-primary' : 'bg-muted',
                  )}
                >
                  <span
                    className={cn(
                      'pointer-events-none block size-5 translate-x-0.5 rounded-full bg-background shadow transition-transform',
                      webSearchEnabled && 'translate-x-[1.15rem]',
                    )}
                  />
                </button>
              </div>
              {!hidePersonaInMenu && (
                <button
                  type="button"
                  role="menuitem"
                  className="flex h-9 w-full cursor-default items-center gap-2 rounded-md px-2 text-left text-sm text-foreground outline-none hover:bg-accent hover:text-accent-foreground"
                  disabled
                >
                  <PersonaGlyph
                    kind="menu"
                    iconUrl={personaIconUrl}
                    emoji={personaEmoji}
                    className="text-muted-foreground"
                  />
                  <span className="truncate">Persona: {personaDisplayName}</span>
                </button>
              )}
            </div>
          </div>,
          document.body,
        )}
      <input
        ref={uploadInputRef}
        type="file"
        className="hidden"
        onChange={async (e) => {
          const file = e.target.files?.[0]
          if (!file) return
          e.target.value = ''
          const text = await file.text().catch(() => null)
          if (text == null) {
            setToastMsg('Could not read file')
            setTimeout(() => setToastMsg(null), 3000)
            return
          }
          setAttachedFiles((prev) => {
            if (prev.find((f) => f.filename === file.name)) return prev
            return [...prev, { filename: file.name, path: file.name, content: text }]
          })
        }}
      />
      <FileBrowserPanel
        isOpen={fileBrowserOpen}
        onClose={() => setFileBrowserOpen(false)}
        rootPath={dawSyncFolder || undefined}
        onFileSelect={async (filename, path, content) => {
          setAttachedFiles((prev) => {
            if (prev.find((f) => f.path === path)) return prev
            return [...prev, { filename, path, content }]
          })
          setFileBrowserOpen(false)
        }}
      />
      {skillsModalOpen &&
        createPortal(
          <div
            className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/50 p-4"
            role="dialog"
            aria-modal="true"
            aria-label="Skills"
            onClick={() => setSkillsModalOpen(false)}
          >
            <div
              className="w-full max-w-2xl overflow-hidden rounded-lg border border-border bg-popover shadow-lg"
              style={{ maxHeight: '80dvh' }}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="border-b border-border bg-muted/30 px-4 py-3">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Skills</h2>
                  <button
                    type="button"
                    onClick={() => setSkillsModalOpen(false)}
                    aria-label="Close"
                    className="rounded-md p-1 outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <X className="size-4" aria-hidden />
                  </button>
                </div>
                <p className="mt-1 text-sm text-muted-foreground">
                  Manage AI skills for this chat session
                </p>
              </div>
              <div className="flex flex-col overflow-y-auto" style={{ maxHeight: 'calc(80dvh - 100px)' }}>
                {/* Session Skills Section */}
                <div className="border-b border-border px-4 py-3">
                  <h3 className="text-sm font-medium text-muted-foreground">Session Skills</h3>
                  <p className="text-xs text-muted-foreground">
                    Active only for this chat. These will be added to your system prompt.
                  </p>
                  {sessionSkillIds.length === 0 ? (
                    <div className="mt-2 rounded-md border border-dashed border-border bg-muted/30 px-4 py-8 text-center">
                      <p className="text-sm text-muted-foreground">No session skills active</p>
                      <button
                        type="button"
                        className="mt-2 text-sm text-primary hover:underline"
                        onClick={() => {
                          // Navigate to skills library or open add dialog
                          window.location.href = '/skills'
                          setSkillsModalOpen(false)
                        }}
                      >
                        Browse Skills Library
                      </button>
                    </div>
                  ) : (
                    <div className="mt-2 flex flex-wrap gap-2">
                      {skillsModalData.sessionSkills.map((skill) => (
                        <span
                          key={skill.id}
                          className="flex items-center gap-1 rounded-md border border-border bg-muted px-2 py-1 text-sm"
                        >
                          <span className="max-w-[150px] truncate">{skill.name}</span>
                          <button
                            type="button"
                            onClick={() => {
                              setSessionSkillIds((prev) => prev.filter((id) => id !== skill.id))
                            }}
                            aria-label={`Remove ${skill.name}`}
                            className="inline-flex size-4 items-center justify-center rounded outline-none transition-colors hover:bg-destructive/15 hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring"
                          >
                            <X className="size-3" aria-hidden />
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                {/* DAW Skills Section */}
                <div className="px-4 py-3">
                  <h3 className="text-sm font-medium text-muted-foreground">DAW Skills</h3>
                  <p className="text-xs text-muted-foreground">
                    Persistent skills attached to this DAW. Manage in DAW Settings.
                  </p>
                  {skillsModalData.dawSkills.length === 0 ? (
                    <div className="mt-2 rounded-md border border-dashed border-border bg-muted/30 px-4 py-6 text-center">
                      <p className="text-sm text-muted-foreground">No DAW skills attached</p>
                      <p className="text-xs text-muted-foreground mt-1">(Manage in DAW Settings)</p>
                    </div>
                  ) : (
                    <div className="mt-2 space-y-1">
                      {skillsModalData.dawSkills.map((skill) => (
                        <div
                          key={skill.id}
                          className="flex items-center justify-between rounded-md border border-border bg-muted/30 px-3 py-2"
                        >
                          <div className="flex items-center gap-2">
                            <span className={`h-2 w-2 rounded-full ${skill.active ? 'bg-primary' : 'bg-muted-foreground/40'}`} />
                            <span className="min-w-0 flex-1 truncate text-sm">{skill.name}</span>
                          </div>
                          <span className="text-xs text-muted-foreground">{(skill.active ? 'Active' : 'Inactive')}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
              <div className="border-t border-border bg-muted/30 px-4 py-3">
                <button
                  type="button"
                  className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
                  onClick={() => setSkillsModalOpen(false)}
                >
                  Done
                </button>
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}
