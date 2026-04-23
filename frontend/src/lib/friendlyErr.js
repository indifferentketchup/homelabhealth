export function friendlyErr(e, fallback) {
  const raw = e?.message || fallback
  try {
    const parsed = JSON.parse(raw)
    if (parsed?.detail) return String(parsed.detail)
  } catch {
    /* not JSON — use raw */
  }
  return raw
}
