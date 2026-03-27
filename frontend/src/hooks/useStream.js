import { useCallback, useRef } from 'react'

/** Incremented on each `consumeStream` call so AbortError can tell "replaced by newer stream" from Stop / guard abort. */
let consumeStreamGeneration = 0

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

  // Do not abort on hook unmount: React Strict Mode (dev) remounts components and would cancel
  // every in-flight chat stream. ChatView still aborts when switching threads; Stop calls abort();
  // starting a new stream aborts the previous via consumeStream().

  const consumeStream = useCallback(
    /**
     * @param {{
     *   url: string
     *   init?: RequestInit
     *   body?: unknown
     *   onToken?: (chunk: string) => void
     *   onSearchSources?: (sources: Array<{ title: string; url: string }>) => void
     *   onTitleUpdate?: (title: string) => void
     *   onDone?: () => void
     *   onError?: (err: Error) => void
     * }} opts
     */
    async (opts) => {
      const myGen = ++consumeStreamGeneration
      const {
        url,
        init = {},
        body,
        onToken,
        onSearchSources,
        onTitleUpdate,
        onDone,
        onError,
      } = opts
      abort()
      const ac = new AbortController()
      abortRef.current = ac
      const headers = new Headers(init.headers)
      let reqBody = init.body
      if (body !== undefined) {
        headers.set('Content-Type', 'application/json')
        reqBody = JSON.stringify(body)
      }

      function processDataLine(data) {
        if (data === '[DONE]') {
          return { kind: 'done' }
        }
        try {
          const obj = JSON.parse(data)
          if (obj.error) {
            return { kind: 'error', err: new Error(String(obj.error)) }
          }
          if (obj.type === 'search_sources' && Array.isArray(obj.sources)) {
            onSearchSources?.(obj.sources)
            return { kind: 'ok' }
          }
          if (obj.type === 'title_update' && typeof obj.title === 'string') {
            onTitleUpdate?.(obj.title)
            return { kind: 'ok' }
          }
          if (obj.content) onToken?.(String(obj.content))
          return { kind: 'ok' }
        } catch (e) {
          if (e instanceof SyntaxError) return { kind: 'ok' }
          return { kind: 'error', err: e instanceof Error ? e : new Error(String(e)) }
        }
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
        let doneCalled = false
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += decoder.decode(value, { stream: true })
          const { events, rest } = parseSseBlocks(buf)
          buf = rest
          for (const data of events) {
            const r = processDataLine(data)
            if (r.kind === 'error') {
              onError?.(r.err)
              abortRef.current = null
              return
            }
            if (r.kind === 'done' && !doneCalled) {
              doneCalled = true
              onDone?.()
            }
          }
        }
        if (buf.trim()) {
          const { events } = parseSseBlocks(`${buf}\n\n`)
          for (const data of events) {
            const r = processDataLine(data)
            if (r.kind === 'error') {
              onError?.(r.err)
              return
            }
            if (r.kind === 'done' && !doneCalled) {
              doneCalled = true
              onDone?.()
            }
          }
        }
        if (!doneCalled) onDone?.()
      } catch (e) {
        if (e?.name === 'AbortError') {
          // Starting a newer stream calls `abort()` first; that AbortError must not clear UI state.
          if (myGen === consumeStreamGeneration) {
            onError?.(e instanceof Error ? e : new Error(String(e)))
          }
          return
        }
        onError?.(e instanceof Error ? e : new Error(String(e)))
      } finally {
        abortRef.current = null
      }
    },
    [abort],
  )

  return { consumeStream, abort }
}
