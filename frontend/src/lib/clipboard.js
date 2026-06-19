// Copy text to the clipboard with a fallback for non-secure contexts.
//
// navigator.clipboard is only defined on HTTPS or localhost. This app is
// self-hosted and usually reached over plain HTTP on a LAN / Tailscale IP,
// where the async Clipboard API is unavailable, so we fall back to a hidden
// textarea + execCommand('copy'). Returns true on success, false otherwise.
export async function copyText(text) {
  const value = text ?? ''
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return true
    } catch {
      // Fall through to the legacy path (permission denied, insecure context).
    }
  }

  try {
    const ta = document.createElement('textarea')
    ta.value = value
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
