import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function SetupPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)

  function handleConfirmBlur() {
    if (confirm && password !== confirm) {
      setError('Passwords do not match.')
    } else if (error === 'Passwords do not match.') {
      setError('')
    }
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        setError(data.detail === 'setup_already_complete' ? 'Account already created.' : 'Setup failed.')
        return
      }
      // Auto-login after setup
      await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
        credentials: 'same-origin',
      })
      window.location.href = '/'
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4 rounded-lg border border-border bg-card p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-foreground">Welcome to HomeLab Health</h1>
        <p className="text-sm text-muted-foreground">Create your account to get started.</p>
        {error && (
          <p id="setup-error" role="alert" className="text-sm text-destructive">
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
              autoComplete="new-password"
              required
              className="pr-9"
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
        <div className="space-y-1">
          <Label htmlFor="confirm">Confirm password</Label>
          <div className="relative">
            <Input
              id="confirm"
              type={showConfirm ? 'text' : 'password'}
              placeholder="Confirm password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              onBlur={handleConfirmBlur}
              autoComplete="new-password"
              required
              className="pr-9"
              aria-describedby={error ? 'setup-error' : undefined}
            />
            <button
              type="button"
              className="absolute inset-y-0 right-0 flex items-center px-2.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-r-lg"
              onClick={() => setShowConfirm(v => !v)}
              aria-label={showConfirm ? 'Hide confirm password' : 'Show confirm password'}
              aria-pressed={showConfirm}
            >
              {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? 'Creating account...' : 'Create account'}
        </Button>
      </form>
    </div>
  )
}
