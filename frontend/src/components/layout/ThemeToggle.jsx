import { Sun, Moon, Monitor } from 'lucide-react'
import { useAppStore } from '@/store/index.js'
import { cn } from '@/lib/utils'

const OPTIONS = [
  { value: 'light', label: 'Light', Icon: Sun },
  { value: 'system', label: 'System', Icon: Monitor },
  { value: 'dark', label: 'Dark', Icon: Moon },
]

export default function ThemeToggle() {
  const theme = useAppStore((s) => s.theme)
  const setTheme = useAppStore((s) => s.setTheme)
  return (
    <div
      className="inline-flex items-center rounded-full border border-border bg-card p-0.5"
      role="radiogroup"
      aria-label="Theme"
    >
      {OPTIONS.map((opt) => {
        const { value, label } = opt
        const Icon = opt.Icon
        const active = theme === value
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={label}
            title={label}
            onClick={() => setTheme(value)}
            className={cn(
              'inline-flex h-11 w-11 items-center justify-center rounded-full transition-colors',
              active
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
          </button>
        )
      })}
    </div>
  )
}
