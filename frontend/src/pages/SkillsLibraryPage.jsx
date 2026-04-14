import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.jsx'
import { Button } from '@/components/ui/button.jsx'
import { Input } from '@/components/ui/input.jsx'
import { Textarea } from '@/components/ui/textarea.jsx'
import { Label } from '@/components/ui/label.jsx'
import { Badge } from '@/components/ui/badge.jsx'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog.jsx'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs.jsx'
import { Alert, AlertDescription } from '@/components/ui/alert.jsx'
import { X, Plus, Link as LinkIcon, Search, FileText, Trash2, ExternalLink } from 'lucide-react'
import {
  listSkills,
  createSkill,
  deleteSkill,
  fetchSkillFromUrl,
  searchSkills,
} from '@/api/skills'

export function SkillsLibraryPage() {
  const queryClient = useQueryClient()
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [urlInput, setUrlInput] = useState('')
  const [nameInput, setNameInput] = useState('')
  const [descriptionInput, setDescriptionInput] = useState('')
  const [rawContentInput, setRawContentInput] = useState('')
  const [tagsInput, setTagsInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [isSearching, setIsSearching] = useState(false)
  const [fetchingUrl, setFetchingUrl] = useState(false)

  const { data: skills, isLoading } = useQuery({
    queryKey: ['skills'],
    queryFn: listSkills,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteSkill,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
    },
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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      setAddDialogOpen(false)
      setUrlInput('')
    },
  })

  const searchMutation = useMutation({
    mutationFn: (query) => searchSkills(query),
    onSuccess: (data) => {
      setSearchResults(data.results || [])
    },
    onError: () => {
      setSearchResults([])
    },
  })

  const resetForm = () => {
    setNameInput('')
    setDescriptionInput('')
    setRawContentInput('')
    setTagsInput('')
    setUrlInput('')
    setSearchQuery('')
    setSearchResults([])
  }

  const handleCreate = () => {
    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t.length > 0)
    createMutation.mutate({
      name: nameInput,
      description: descriptionInput || null,
      raw_content: rawContentInput,
      tags: tags.length > 0 ? tags : null,
    })
  }

  const handleFetchUrl = () => {
    if (!urlInput.trim()) return
    setFetchingUrl(true)
    fetchUrlMutation.mutate(urlInput, {
      onSettled: () => setFetchingUrl(false),
    })
  }

  const handleSearch = () => {
    if (!searchQuery.trim()) return
    setIsSearching(true)
    searchMutation.mutate(searchQuery, {
      onSettled: () => setIsSearching(false),
    })
  }

  const handleSaveFromSearch = (skillPath) => {
    // skillPath is like "owner/repo/skill-name"
    const url = `skills.sh/${skillPath}`
    setUrlInput(url)
    // Auto-fetch
    setFetchingUrl(true)
    fetchUrlMutation.mutate(url, {
      onSettled: () => {
        setFetchingUrl(false)
        setSearchQuery('')
        setSearchResults([])
      },
    })
  }

  if (isLoading) {
    return <div className="flex items-center justify-center h-64">Loading...</div>
  }

  return (
    <div className="container mx-auto p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Skills Library</h1>
        <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={() => resetForm()}>
              <Plus className="w-4 h-4 mr-2" />
              Add Skill
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
            <DialogHeader>
              <DialogTitle>Add New Skill</DialogTitle>
              <DialogDescription>
                Add a skill to your library. Skills are AI instructions that can be attached to DAWs or individual chats.
              </DialogDescription>
            </DialogHeader>
            <Tabs defaultValue="url" className="w-full">
              <TabsList className="grid w-full grid-cols-3">
                <TabsTrigger value="url">
                  <LinkIcon className="w-4 h-4 mr-2" />
                  From URL
                </TabsTrigger>
                <TabsTrigger value="search">
                  <Search className="w-4 h-4 mr-2" />
                  Search
                </TabsTrigger>
                <TabsTrigger value="raw">
                  <FileText className="w-4 h-4 mr-2" />
                  Raw Markdown
                </TabsTrigger>
              </TabsList>

              <TabsContent value="url" className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="url">URL (skills.sh or raw GitHub)</Label>
                  <div className="flex gap-2">
                    <Input
                      id="url"
                      value={urlInput}
                      onChange={(e) => setUrlInput(e.target.value)}
                      placeholder="skills.sh/owner/repo/skill or https://raw.githubusercontent.com/..."
                    />
                    <Button onClick={handleFetchUrl} disabled={fetchingUrl || !urlInput.trim()}>
                      {fetchingUrl ? 'Fetching...' : 'Fetch'}
                    </Button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Supports skills.sh URLs (auto-converts to raw GitHub) or direct raw markdown URLs
                  </p>
                </div>
              </TabsContent>

              <TabsContent value="search" className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="search">Search skills.sh</Label>
                  <div className="flex gap-2">
                    <Input
                      id="search"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      placeholder="Search for skills..."
                    />
                    <Button onClick={handleSearch} disabled={isSearching || !searchQuery.trim()}>
                      {isSearching ? 'Searching...' : 'Search'}
                    </Button>
                  </div>
                </div>
                {searchResults.length > 0 && (
                  <div className="max-h-64 overflow-y-auto space-y-2">
                    {searchResults.map((result, idx) => (
                      <Card key={idx} className="cursor-pointer hover:bg-muted/50" onClick={() => handleSaveFromSearch(result.skill_path)}>
                        <CardContent className="p-3">
                          <div className="font-medium text-sm">{result.title}</div>
                          <div className="text-xs text-muted-foreground truncate">{result.url}</div>
                          <div className="text-xs text-muted-foreground mt-1">{result.snippet}</div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </TabsContent>

              <TabsContent value="raw" className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Name</Label>
                  <Input
                    id="name"
                    value={nameInput}
                    onChange={(e) => setNameInput(e.target.value)}
                    placeholder="Skill Name"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="description">Description (optional)</Label>
                  <Input
                    id="description"
                    value={descriptionInput}
                    onChange={(e) => setDescriptionInput(e.target.value)}
                    placeholder="Brief description..."
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="tags">Tags (comma-separated, optional)</Label>
                  <Input
                    id="tags"
                    value={tagsInput}
                    onChange={(e) => setTagsInput(e.target.value)}
                    placeholder="coding, python, debugging"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="content">Markdown Content</Label>
                  <Textarea
                    id="content"
                    value={rawContentInput}
                    onChange={(e) => setRawContentInput(e.target.value)}
                    placeholder="# Skill Name\nDescription...\n\nInstructions for the AI..."
                    rows={10}
                    className="font-mono text-sm"
                  />
                </div>
              </TabsContent>
            </Tabs>
            <DialogFooter>
              {urlInput && (
                <Button variant="ghost" size="sm" onClick={() => setUrlInput('')}>
                  <X className="w-4 h-4" />
                </Button>
              )}
              {rawContentInput && (
                <Button onClick={handleCreate} disabled={!nameInput.trim() || !rawContentInput.trim() || createMutation.isPending}>
                  {createMutation.isPending ? 'Creating...' : 'Create Skill'}
                </Button>
              )}
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {skills && skills.length === 0 ? (
        <Alert>
          <AlertDescription>No skills in your library yet. Click "Add Skill" to get started.</AlertDescription>
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
                    {skill.source_url.replace('https://', '').replace('http://', '').substring(0, 50)}
                    {skill.source_url.length > 50 ? '...' : ''}
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
