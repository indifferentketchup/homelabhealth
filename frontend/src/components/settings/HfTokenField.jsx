import { useCallback, useEffect, useState } from 'react'

import { getHfToken, putHfToken, deleteHfToken } from '@/api/system'
import { Button } from '@/components/ui/button'

export default function HfTokenField() {
  const [state, setState] = useState({ configured: false, masked: null, updated_at: null })
  const [editing, setEditing] = useState(false)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const s = await getHfToken()
      setState(s)
      setErr(null)
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Failed to load HF token state')
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  async function onSave() {
    setBusy(true); setErr(null)
    try {
      await putHfToken(token)
      setEditing(false); setToken('')
      await refresh()
    } catch (e) {
      const raw = e instanceof Error ? e.message : 'Save failed'
      let pretty = raw
      try {
        const parsed = JSON.parse(raw)
        if (parsed?.detail) pretty = String(parsed.detail)
      } catch { /* not JSON */ }
      setErr(pretty)
    } finally {
      setBusy(false)
    }
  }

  async function onClear() {
    setBusy(true); setErr(null)
    try {
      await deleteHfToken()
      await refresh()
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Clear failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4" data-testid="hf-token-field">
      <h3 className="text-sm font-medium text-foreground">HuggingFace token</h3>
      <p className="mt-1 text-xs text-muted-foreground">
        Required for MedGemma (gated). Paste your HuggingFace read token.
      </p>

      {state.configured && !editing ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono text-foreground" data-testid="hf-token-masked">
            {state.masked}
          </span>
          {state.updated_at ? (
            <span className="text-xs text-muted-foreground">
              · saved {new Date(state.updated_at).toLocaleString()}
            </span>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => { setEditing(true); setToken('') }}
            disabled={busy}
            data-testid="hf-token-edit"
          >
            Edit
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void onClear()}
            disabled={busy}
            data-testid="hf-token-clear"
          >
            Clear
          </Button>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            type="password"
            placeholder="Paste HF Token Here"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            disabled={busy}
            className="flex-1 min-w-[260px] rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground"
            data-testid="hf-token-input"
          />
          <Button
            type="button"
            size="sm"
            onClick={() => void onSave()}
            disabled={busy || !token.trim()}
            data-testid="hf-token-save"
          >
            Save
          </Button>
          {editing ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => { setEditing(false); setToken('') }}
              disabled={busy}
            >
              Cancel
            </Button>
          ) : null}
        </div>
      )}

      {err ? (
        <p className="mt-2 text-xs text-destructive" data-testid="hf-token-error">{err}</p>
      ) : null}

      <details className="mt-3 text-xs text-muted-foreground" data-testid="hf-token-show-me-how">
        <summary className="cursor-pointer text-foreground hover:text-primary">
          Show me how
        </summary>
        <ol className="ml-5 mt-2 list-decimal space-y-1">
          <li>
            Sign in (or sign up) at{' '}
            <a
              href="https://huggingface.co/join"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              huggingface.co/join
            </a>.
          </li>
          <li>
            Visit{' '}
            <a
              href="https://huggingface.co/settings/tokens"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              huggingface.co/settings/tokens
            </a>{' '}
            and click <strong>Create new token</strong>.
          </li>
          <li>
            Pick <strong>Read</strong> access. Name it anything (e.g. <code>homelabhealth</code>).
          </li>
          <li>
            Copy the token (starts with <code>hf_</code>) and paste it above. Click <strong>Save</strong>.
          </li>
          <li>
            For MedGemma (or any gated model): open the model page (e.g.{' '}
            <a
              href="https://huggingface.co/google/medgemma-4b-it"
              target="_blank"
              rel="noopener noreferrer"
              className="text-primary underline"
            >
              google/medgemma-4b-it
            </a>
            ) while signed in, then click <strong>Agree and access repository</strong>. Pulls won&apos;t
            work until both the token AND the license click are done.
          </li>
        </ol>
      </details>
    </div>
  )
}
