import { Phone } from 'lucide-react'

const CRISIS_KEYWORDS = [
  'suicide', 'suicidal', 'kill myself', 'end my life', 'self-harm',
  'self harm', 'overdose', 'crisis', '988', 'poison',
  'emergency services', 'call 911',
]

export function detectCrisis(text) {
  if (!text) return false
  const lower = text.toLowerCase()
  return CRISIS_KEYWORDS.some(kw => lower.includes(kw))
}

const HOTLINES = [
  { name: '988 Suicide & Crisis Lifeline', number: '988', description: 'Call or text 24/7' },
  { name: 'Poison Control', number: '1-800-222-1222', description: 'US only' },
  { name: 'Emergency Services', number: '911', description: 'If in immediate danger' },
]

export function CrisisCard() {
  return (
    <div className="mx-auto my-3 max-w-lg rounded-lg border-2 border-destructive/50 bg-destructive/5 p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-destructive">
        <Phone className="size-4" />
        Crisis Resources
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        If you or someone you know is in crisis, contact one of these resources now.
      </p>
      <div className="space-y-2">
        {HOTLINES.map(h => (
          <div key={h.number} className="flex items-baseline justify-between text-sm">
            <div>
              <span className="font-medium">{h.name}</span>
              <span className="ml-2 text-xs text-muted-foreground">{h.description}</span>
            </div>
            <a
              href={`tel:${h.number.replace(/[^0-9+]/g, '')}`}
              className="font-mono font-semibold text-destructive hover:underline"
            >
              {h.number}
            </a>
          </div>
        ))}
      </div>
    </div>
  )
}
