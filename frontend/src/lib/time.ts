export function formatDate(iso?: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString()
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function formatRelative(iso?: string | null): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const abs = Math.abs(diff)
  const future = diff < 0

  if (abs < 60_000) return future ? 'in a moment' : 'just now'
  if (abs < 3_600_000) {
    const m = Math.round(abs / 60_000)
    return future ? `in ${m}m` : `${m}m ago`
  }
  if (abs < 86_400_000) {
    const h = Math.round(abs / 3_600_000)
    return future ? `in ${h}h` : `${h}h ago`
  }
  const d = Math.round(abs / 86_400_000)
  return future ? `in ${d}d` : `${d}d ago`
}

export function formatScheduled(iso?: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const diff = d.getTime() - Date.now()
  if (diff > 0 && diff < 86_400_000) {
    // within 24h future — show relative
    return formatRelative(iso)
  }
  return formatDateTime(iso)
}

export function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}
