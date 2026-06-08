import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        credentials: 'same-origin',
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail === 'invalid_credentials' ? 'Invalid username or password.' : 'Login failed.')
        return
      }
      window.location.href = '/'
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-foreground">HomeLab Health</h1>
        <p className="text-sm text-muted-foreground">Sign in to continue</p>
        {error && (
          <p id="login-error" role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <div className="space-y-1">
          <Label htmlFor="username">Username</Label>
          <Input
            id="username"
            type="text"
            placeholder="Username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoComplete="username"
            autoFocus
            required
            aria-describedby={error ? 'login-error' : undefined}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="password">Password</Label>
          <div className="relative">
            <Input
              id="password"
              type={showPassword ? 'text' : 'password'}
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              className="pr-9"
              aria-describedby={error ? 'login-error' : undefined}
            />
            <button
              type="button"
              className="absolute inset-y-0 right-0 flex items-center px-2.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-r-lg"
              onClick={() => setShowPassword(v => !v)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
            >
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? 'Signing in...' : 'Sign in'}
        </Button>
      </form>
    </div>
  )
}
