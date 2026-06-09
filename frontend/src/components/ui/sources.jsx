import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'
import { BookIcon, ChevronDownIcon } from 'lucide-react'

export function Sources({ className, ...props }) {
  return (
    <Collapsible
      className={cn('not-prose text-sm text-foreground', className)}
      {...props}
    />
  )
}

export function SourcesTrigger({ className, count, children, ...props }) {
  return (
    <CollapsibleTrigger
      className={cn('flex items-center gap-2 group cursor-pointer', className)}
      {...props}
    >
      {children ?? (
        <>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary">
            <BookIcon className="size-3" />
            <span>{count} source{count !== 1 ? 's' : ''}</span>
          </span>
          <ChevronDownIcon className="size-3.5 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
        </>
      )}
    </CollapsibleTrigger>
  )
}

export function SourcesContent({ className, ...props }) {
  return (
    <CollapsibleContent
      className={cn(
        'mt-2 flex w-full flex-col gap-1.5',
        'data-[state=closed]:fade-out-0 data-[state=closed]:slide-out-to-top-2 data-[state=open]:slide-in-from-top-2 outline-none data-[state=closed]:animate-out data-[state=open]:animate-in',
        className,
      )}
      {...props}
    />
  )
}

export function Source({ href, title, children, className, ...props }) {
  const isLink = Boolean(href)
  const Tag = isLink ? 'a' : 'span'
  const linkProps = isLink
    ? { href, target: '_blank', rel: 'noreferrer' }
    : {}

  return (
    <Tag
      className={cn(
        'flex items-center gap-2 rounded-md border border-border/60 bg-card/50 px-2.5 py-1.5 text-sm transition-colors',
        isLink &&
          'hover:bg-accent/5 hover:border-accent/20 cursor-pointer',
        className,
      )}
      {...linkProps}
      {...props}
    >
      {children ?? (
        <>
          <BookIcon className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="block text-sm font-medium leading-snug text-foreground/90">
            {title}
          </span>
        </>
      )}
    </Tag>
  )
}
