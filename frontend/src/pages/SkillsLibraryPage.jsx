import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.jsx'
import { Button } from '@/components/ui/button.jsx'
import { Input } from '@/components/ui/input.jsx'
import { Textarea } from '@/components/ui/textarea.jsx'
import { Label } from '@/components/ui/label.jsx'
import { Badge } from '@/components/ui/badge.jsx'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog.jsx'
import { Alert, AlertDescription } from '@/components/ui/alert.jsx'
import { ScrollArea } from '@/components/ui/scroll-area.jsx'
import {
  Plus,
  Link as LinkIcon,
  Search,
  FileText,
  Trash2,
  ExternalLink,
  Loader2,
  CheckCircle2,
} from 'lucide-react'
import {
  listSkills,
  createSkill,
  deleteSkill,
  fetchSkillFromUrl,
  searchSkills,
} from '@/api/skills'

const TABS = [
  { id: 'url', label: 'From URL', icon: LinkIcon },
  { id: 'search', label: 'Search', icon: Search },
  { id: 'manual', label: 'Write Manually', icon: FileText },
]

function PreviewCard({ name, description, content, sourceUrl, onAdd, pending }) {
  const lines = (content || '').split('\n')
  const previewBody = lines.slice(0, 10).join('\n') + (lines.length > 10 ? '\n…' : '')
  return (
    <Card className="border-border bg-background">
      <CardHeader className="pb-2">
        <div className="flex items-start gap-2">
          <CheckCircle2 className="w-4 h-4 mt-1 text-foreground/70 shrink-0" />
          <div className="min-w-0 flex-1">
            <CardTitle className="text-base truncate">{name || 'Untitled skill'}</CardTitle>
            {description && (
              <CardDescription className="line-clamp-2">{description}</CardDescription>
            )}
            {sourceUrl && (
              <div className="text-xs text-muted-foreground mt-1 truncate">{sourceUrl}</div>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <pre className="bg-muted text-muted-foreground text-xs font-mono p-3 rounded-md overflow-x-auto whitespace-pre max-h-48">
{previewBody}
        </pre>
        <Button
          onClick={onAdd}
          disabled={pending || !name?.trim() || !content?.trim()}
          className="w-full"
        >
          {pending ? (
            <>
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              Adding…
            </>
          ) : (
            'Add to Library'
          )}
        </Button>
      </CardContent>
    </Card>
  )
}

export function SkillsLibraryPage() {
  const queryClient = useQueryClient()
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('url')

  const [urlInput, setUrlInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [fetchError, setFetchError] = useState(null)

  const [nameInput, setNameInput] = useState('')
  const [descriptionInput, setDescriptionInput] = useState('')
  const [rawContentInput, setRawContentInput] = useState('')
  const [sourceUrlInput, setSourceUrlInput] = useState('')
  const [tagsInput, setTagsInput] = useState('')

  const { data: skills, isLoading } = useQuery({
    queryKey: ['skills'],
    queryFn: listSkills,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSkill,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['skills'] }),
  })

  const createMutation = useMutation({
    mutationFn: createSkill,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      setAddDialogOpen(false)
      resetForm()
    },
  })

  const fetchUrlMutation = useMutation({
    mutationFn: fetchSkillFromUrl,
    onSuccess: (data) => {
      setNameInput(data.name || '')
      setDescriptionInput(data.description || '')
      setRawContentInput(data.raw_content || '')
      setSourceUrlInput(data.source_url || '')
      setFetchError(null)
    },
    onError: (err) => {
      setFetchError(err?.message || 'Failed to fetch skill from URL')
    },
  })

  const searchMutation = useMutation({
    mutationFn: (query) => searchSkills(query),
    onSuccess: (data) => setSearchResults(data.results || []),
    onError: () => setSearchResults([]),
  })

  const resetForm = () => {
    setActiveTab('url')
    setUrlInput('')
    setSearchQuery('')
    setSearchResults([])
    setFetchError(null)
    setNameInput('')
    setDescriptionInput('')
    setRawContentInput('')
    setSourceUrlInput('')
    setTagsInput('')
  }

  const handleCreate = () => {
    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t.length > 0)
    createMutation.mutate({
      name: nameInput,
      description: descriptionInput || null,
      source_url: sourceUrlInput || null,
      raw_content: rawContentInput,
      tags: tags.length > 0 ? tags : null,
    })
  }

  const handleFetchUrl = () => {
    if (!urlInput.trim()) return
    setFetchError(null)
    fetchUrlMutation.mutate(urlInput.trim())
  }

  const handleSearch = () => {
    if (!searchQuery.trim()) return
    searchMutation.mutate(searchQuery.trim())
  }

  const handlePickResult = (skillPath) => {
    const url = `https://skills.sh/${skillPath}`
    setFetchError(null)
    fetchUrlMutation.mutate(url)
  }

  const hasPreview = Boolean(rawContentInput)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 h-64 text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Loading…
      </div>
    )
  }

  return (
    <div className="container mx-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Skills Library</h1>
          <p className="text-sm text-muted-foreground">
            Reusable instructions you can attach to DAWs and chats.
          </p>
        </div>
        <Dialog
          open={addDialogOpen}
          onOpenChange={(open) => {
            setAddDialogOpen(open)
            if (!open) resetForm()
          }}
        >
          <DialogTrigger asChild>
            <Button>
              <Plus className="w-4 h-4 mr-2" />
              Add Skill
            </Button>
          </DialogTrigger>
          <DialogContent className="w-[95vw] max-w-5xl min-h-[70vh] max-h-[90vh] p-0 overflow-hidden flex flex-col sm:max-w-5xl">
            <DialogHeader className="px-8 pt-6 pb-4 border-b border-border">
              <DialogTitle className="text-lg">Add a Skill</DialogTitle>
              <DialogDescription>
                Pull from a URL, search the skills.sh index, or paste markdown directly.
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col md:flex-row flex-1 min-h-0">
              <nav className="md:w-48 shrink-0 border-b md:border-b-0 md:border-r border-border p-3 flex md:flex-col gap-1 overflow-x-auto">
                {TABS.map((tab) => {
                  const Icon = tab.icon
                  const active = activeTab === tab.id
                  return (
                    <Button
                      key={tab.id}
                      variant={active ? 'secondary' : 'ghost'}
                      className="justify-start flex-1 min-w-0"
                      onClick={() => setActiveTab(tab.id)}
                    >
                      <Icon className="w-4 h-4 mr-2" />
                      {tab.label}
                    </Button>
                  )
                })}
              </nav>

              <div className="flex-1 overflow-y-auto p-8 space-y-5 min-w-0">
                {activeTab === 'url' && (
                  <div className="space-y-4">
                    {fetchError && (
                      <Alert variant="destructive">
                        <AlertDescription>{fetchError}</AlertDescription>
                      </Alert>
                    )}
                    <div className="space-y-2">
                      <Label htmlFor="url" className="text-sm">Skill URL</Label>
                      <div className="flex gap-2">
                        <Input
                          id="url"
                          value={urlInput}
                          onChange={(e) => setUrlInput(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleFetchUrl()}
                          placeholder="skills.sh/owner/repo/skill   or   https://raw.githubusercontent.com/…"
                          className="flex-1 h-10 text-sm px-3"
                        />
                        <Button
                          onClick={handleFetchUrl}
                          disabled={fetchUrlMutation.isPending || !urlInput.trim()}
                          className="h-10 px-5"
                        >
                          {fetchUrlMutation.isPending ? (
                            <>
                              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                              Fetching…
                            </>
                          ) : (
                            'Fetch'
                          )}
                        </Button>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        skills.sh URLs auto-resolve to raw GitHub. Direct raw markdown links also work.
                      </p>
                    </div>
                    {hasPreview && (
                      <PreviewCard
                        name={nameInput}
                        description={descriptionInput}
                        content={rawContentInput}
                        sourceUrl={sourceUrlInput}
                        onAdd={handleCreate}
                        pending={createMutation.isPending}
                      />
                    )}
                  </div>
                )}

                {activeTab === 'search' && (
                  <div className="space-y-4">
                    {fetchError && (
                      <Alert variant="destructive">
                        <AlertDescription>{fetchError}</AlertDescription>
                      </Alert>
                    )}
                    <div className="space-y-2">
                      <Label htmlFor="search" className="text-sm">Search skills.sh</Label>
                      <div className="flex gap-2">
                        <Input
                          id="search"
                          value={searchQuery}
                          onChange={(e) => setSearchQuery(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                          placeholder="e.g. python debugging, react testing…"
                          className="flex-1 h-10 text-sm px-3"
                        />
                        <Button
                          onClick={handleSearch}
                          disabled={searchMutation.isPending || !searchQuery.trim()}
                          className="h-10 px-5"
                        >
                          {searchMutation.isPending ? (
                            <>
                              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                              Searching…
                            </>
                          ) : (
                            'Search'
                          )}
                        </Button>
                      </div>
                    </div>

                    {searchResults.length > 0 && (
                      <ScrollArea className="h-80 pr-3">
                        <div className="space-y-2">
                          {searchResults.map((result, idx) => (
                            <Card
                              key={idx}
                              className="cursor-pointer hover:bg-muted/50 transition-colors"
                              onClick={() => handlePickResult(result.skill_path)}
                            >
                              <CardContent className="p-3">
                                <div className="font-medium text-sm truncate">{result.title}</div>
                                <div className="text-xs text-muted-foreground truncate">
                                  {result.url}
                                </div>
                                {result.snippet && (
                                  <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                    {result.snippet}
                                  </div>
                                )}
                              </CardContent>
                            </Card>
                          ))}
                        </div>
                      </ScrollArea>
                    )}

                    {hasPreview && (
                      <PreviewCard
                        name={nameInput}
                        description={descriptionInput}
                        content={rawContentInput}
                        sourceUrl={sourceUrlInput}
                        onAdd={handleCreate}
                        pending={createMutation.isPending}
                      />
                    )}
                  </div>
                )}

                {activeTab === 'manual' && (
                  <div className="space-y-5">
                    <div className="grid gap-5 md:grid-cols-2">
                      <div className="space-y-2">
                        <Label htmlFor="name" className="text-sm">Name</Label>
                        <Input
                          id="name"
                          value={nameInput}
                          onChange={(e) => setNameInput(e.target.value)}
                          placeholder="Skill name"
                          className="h-10 text-sm px-3"
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="tags" className="text-sm">Tags (comma-separated)</Label>
                        <Input
                          id="tags"
                          value={tagsInput}
                          onChange={(e) => setTagsInput(e.target.value)}
                          placeholder="coding, python, debugging"
                          className="h-10 text-sm px-3"
                        />
                      </div>
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="description" className="text-sm">Description (optional)</Label>
                      <Input
                        id="description"
                        value={descriptionInput}
                        onChange={(e) => setDescriptionInput(e.target.value)}
                        placeholder="Brief description…"
                        className="h-10 text-sm px-3"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="content" className="text-sm">Markdown content</Label>
                      <Textarea
                        id="content"
                        value={rawContentInput}
                        onChange={(e) => setRawContentInput(e.target.value)}
                        placeholder={'# Skill Name\nDescription…\n\nInstructions for the AI…'}
                        rows={18}
                        className="font-mono text-sm w-full resize-none"
                      />
                    </div>
                    <Button
                      onClick={handleCreate}
                      disabled={
                        createMutation.isPending ||
                        !nameInput.trim() ||
                        !rawContentInput.trim()
                      }
                      className="w-full h-10"
                    >
                      {createMutation.isPending ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Adding…
                        </>
                      ) : (
                        'Add to Library'
                      )}
                    </Button>
                  </div>
                )}
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {skills && skills.length === 0 ? (
        <Alert>
          <AlertDescription>
            No skills in your library yet. Click "Add Skill" to get started.
          </AlertDescription>
        </Alert>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {skills?.map((skill) => (
            <Card key={skill.id}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <CardTitle className="text-lg">{skill.name}</CardTitle>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => deleteMutation.mutate(skill.id)}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="w-4 h-4 text-destructive" />
                  </Button>
                </div>
                {skill.description && (
                  <CardDescription className="line-clamp-2">{skill.description}</CardDescription>
                )}
              </CardHeader>
              <CardContent>
                {skill.tags && skill.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mb-2">
                    {skill.tags.map((tag, i) => (
                      <Badge key={i} variant="secondary" className="text-xs">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
                {skill.source_url && (
                  <a
                    href={skill.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:underline flex items-center gap-1"
                  >
                    <ExternalLink className="w-3 h-3" />
                    {skill.source_url.replace(/^https?:\/\//, '').substring(0, 50)}
                    {skill.source_url.length > 50 ? '…' : ''}
                  </a>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
