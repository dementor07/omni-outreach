/** Full display name from a lead/message row */
export function fullName(row: any): string {
  if (!row) return 'Unknown'
  const n = [row.first_name, row.last_name].filter(Boolean).join(' ').trim()
  return n || (row.linkedin_url as string) || (row.email as string) || 'Unknown'
}

/** Human-readable relative timestamp */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (isNaN(t)) return '—'
  const diff = Date.now() - t
  const s = Math.max(0, Math.floor(diff / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  if (d < 7) return `${d}d ago`
  return new Date(iso).toLocaleDateString()
}

/** Format a scheduled-at timestamp */
export function formatScheduled(iso: string | null | undefined): string {
  if (!iso) return '—'
  const t = new Date(iso)
  if (isNaN(t.getTime())) return '—'
  const now = new Date()
  const sameDay = t.toDateString() === now.toDateString()
  const time = t.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return sameDay ? `Today, ${time}` : `${t.toLocaleDateString([], { month: 'short', day: 'numeric' })}, ${time}`
}

/** Build a query string from an object, omitting empty values */
export function buildQuery(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams()
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}
