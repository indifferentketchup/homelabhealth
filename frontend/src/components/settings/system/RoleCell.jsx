import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const ROLE_DISPLAY = {
  chat:         { label: 'Chat',      desc: 'Answers your questions using health context' },
  tasks:        { label: 'Tasks',     desc: 'Handles background jobs like summarization' },
  embed:        { label: 'Search',    desc: 'Converts text into vectors so documents can be found' },
  rerank:       { label: 'Relevance', desc: 'Re-scores search results for accuracy' },
  vision:       { label: 'Vision',    desc: 'Understands medical images for chat' },
}

export function RoleCell({ role }) {
  const display = ROLE_DISPLAY[role]
  if (!display) return <span className="font-medium text-foreground">{role}</span>
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="font-medium text-foreground cursor-default border-b border-dotted border-muted-foreground/30">
          {display.label}
        </span>
      </TooltipTrigger>
      <TooltipContent side="top">
        <p className="text-xs">{display.desc}</p>
        <p className="font-mono text-[10px] text-muted-foreground mt-0.5">{role}</p>
      </TooltipContent>
    </Tooltip>
  )
}
