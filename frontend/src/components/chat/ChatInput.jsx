import { useQuery } from '@tanstack/react-query'
import { Cpu, FileUp, Music, Plus, Search, SendHorizontal, Square, UserCircle } from 'lucide-react'

import { fetchOllamaModels } from '@/api/ollama.js'
import { patchChat } from '@/api/chats.js'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

const CLAUDE_OPTIONS = [
  { value: 'claude-sonnet', label: 'Claude Sonnet' },
  { value: 'claude-haiku', label: 'Claude Haiku' },
  { value: 'claude-opus', label: 'Claude Opus' },
]

export function ChatInput({
  value,
  onChange,
  onSend,
  disabled,
  streaming,
  onStop,
  activeChatId,
}) {
  const selectedModel = useAppStore((s) => s.selectedModel)
  const setSelectedModel = useAppStore((s) => s.setSelectedModel)
  const webSearchEnabled = useAppStore((s) => s.webSearchEnabled)
  const setWebSearchEnabled = useAppStore((s) => s.setWebSearchEnabled)

  const { data: tags } = useQuery({
    queryKey: ['ollama', 'models'],
    queryFn: fetchOllamaModels,
    staleTime: 60_000,
  })

  const ollamaModels = Array.isArray(tags?.models) ? tags.models.map((m) => m.name).filter(Boolean) : []

  async function applyModel(next) {
    setSelectedModel(next)
    if (activeChatId) {
      try {
        await patchChat(activeChatId, { model: next })
      } catch {
        /* ignore */
      }
    }
  }

  async function applyWebSearch(next) {
    setWebSearchEnabled(next)
    if (activeChatId) {
      try {
        await patchChat(activeChatId, { web_search_enabled: next })
      } catch {
        /* ignore */
      }
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!streaming && !disabled) onSend()
    }
  }

  return (
    <div className="border-t border-border bg-background p-3">
      <div className="mx-auto flex max-w-[52rem] items-end gap-2">
        <Popover modal={false}>
          <PopoverTrigger asChild>
            <Button type="button" variant="outline" size="icon" className="shrink-0 border-border" aria-label="More actions">
              <Plus className="size-4" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-64 space-y-1 p-2" align="start">
            <Button type="button" variant="ghost" className="h-9 w-full justify-start gap-2 px-2" disabled>
              <FileUp className="size-4 text-muted-foreground" />
              Upload files
            </Button>
            <div className="flex items-center justify-between gap-2 rounded-md px-2 py-1.5">
              <span className="flex items-center gap-2 text-sm text-foreground">
                <Search className="size-4 text-muted-foreground" />
                Web search
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={webSearchEnabled}
                onClick={() => applyWebSearch(!webSearchEnabled)}
                className={cn(
                  'relative inline-flex h-6 w-10 shrink-0 rounded-full border border-border transition-colors',
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
            <Button type="button" variant="ghost" className="h-9 w-full justify-start gap-2 px-2" disabled>
              <UserCircle className="size-4 text-muted-foreground" />
              Persona
            </Button>
            <Button type="button" variant="ghost" className="h-9 w-full justify-start gap-2 px-2" disabled>
              <Music className="size-4 text-muted-foreground" />
              Add to DAW
            </Button>
            <DropdownMenu modal={false}>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="ghost" className="h-9 w-full justify-start gap-2 px-2">
                  <Cpu className="size-4 text-muted-foreground" />
                  Change model
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="max-h-72 w-56" align="start">
                <DropdownMenuLabel>Ollama</DropdownMenuLabel>
                {ollamaModels.length === 0 ? (
                  <DropdownMenuItem disabled>No models loaded</DropdownMenuItem>
                ) : (
                  ollamaModels.map((name) => (
                    <DropdownMenuItem key={name} onClick={() => applyModel(name)}>
                      <span className={cn(name === selectedModel && 'text-primary')}>{name}</span>
                    </DropdownMenuItem>
                  ))
                )}
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Claude</DropdownMenuLabel>
                {CLAUDE_OPTIONS.map((o) => (
                  <DropdownMenuItem key={o.value} onClick={() => applyModel(o.value)}>
                    <span className={cn(o.value === selectedModel && 'text-primary')}>{o.label}</span>
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </PopoverContent>
        </Popover>

        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message… (Enter to send, Shift+Enter for newline)"
          disabled={disabled || streaming}
          rows={2}
          className="min-h-[2.75rem] flex-1 resize-none rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground outline-none ring-ring placeholder:text-muted-foreground focus-visible:ring-2"
        />

        {streaming ? (
          <Button type="button" variant="secondary" size="icon" className="shrink-0" onClick={onStop} aria-label="Stop">
            <Square className="size-4" />
          </Button>
        ) : (
          <Button
            type="button"
            size="icon"
            className="shrink-0"
            onClick={onSend}
            disabled={disabled || !value.trim()}
            aria-label="Send"
          >
            <SendHorizontal className="size-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
