import { useCallback, useEffect, useRef } from 'react'

function parseSseBlocks(buffer) {
  const events = []
  let rest = buffer
  let idx
  while ((idx = rest.indexOf('\n\n')) >= 0) {
    const block = rest.slice(0, idx)
    rest = rest.slice(idx + 2)
    const lines = block.split('\n')
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        events.push(line.slice(6).trim())
      }
    }
  }
  return { events, rest }
}

/**
 * SSE consumer for FastAPI text/event-stream (data: JSON or [DONE]).
 */
export function useStream() {
  const abortRef = useRef(null)

  const abort = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  useEffect(() => () => abort(), [abort])

  const consumeStream = useCallback(
    /**
     * @param {{
     *   url: string
     *   init?: RequestInit
     *   body?: unknown
     *   onToken?: (chunk: string) => void
     *   onDone?: () => void
     *   onError?: (err: Error) => void
     * }} opts
     */
    async (opts) => {
      const { url, init = {}, body, onToken, onDone, onError } = opts
      abort()
      const ac = new AbortController()
      abortRef.current = ac
      const headers = new Headers(init.headers)
      let reqBody = init.body
      if (body !== undefined) {
        headers.set('Content-Type', 'application/json')
        reqBody = JSON.stringify(body)
      }
      try {
        const res = await fetch(url, {
          ...init,
          method: init.method || 'POST',
          headers,
          body: reqBody,
          signal: ac.signal,
        })
        if (!res.ok) {
          const t = await res.text().catch(() => '')
          onError?.(new Error(t || res.statusText || String(res.status)))
          return
        }
        const reader = res.body?.getReader()
        if (!reader) {
          onError?.(new Error('No response body'))
          return
        }
        const decoder = new TextDecoder()
        let buf = ''
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const { events, rest } = parseSseBlocks(buf)
          buf = rest
          for (const data of events) {
            if (data === '[DONE]') {
              onDone?.()
              abortRef.current = null
              return
            }
            try {
              const obj = JSON.parse(data)
              if (obj.error) {
                onError?.(new Error(String(obj.error)))
                abortRef.current = null
                return
              }
              if (obj.content) onToken?.(String(obj.content))
            } catch (e) {
              if (e instanceof SyntaxError) continue
              onError?.(e instanceof Error ? e : new Error(String(e)))
              abortRef.current = null
              return
            }
          }
        }
        if (buf.trim()) {
          const { events } = parseSseBlocks(`${buf}\n\n`)
          for (const data of events) {
            if (data === '[DONE]') {
              onDone?.()
              return
            }
            try {
              const obj = JSON.parse(data)
              if (obj.error) {
                onError?.(new Error(String(obj.error)))
                return
              }
              if (obj.content) onToken?.(String(obj.content))
            } catch (e) {
              if (!(e instanceof SyntaxError)) {
                onError?.(e instanceof Error ? e : new Error(String(e)))
                return
              }
            }
          }
        }
        onDone?.()
      } catch (e) {
        if (e?.name === 'AbortError') return
        onError?.(e instanceof Error ? e : new Error(String(e)))
      } finally {
        abortRef.current = null
      }
    },
    [abort],
  )

  return { consumeStream, abort }
}
