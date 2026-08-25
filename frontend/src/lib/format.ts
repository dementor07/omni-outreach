interface NamedRow {
  first_name?: string | null
  last_name?: string | null
  linkedin_url?: string | null
  email?: string | null
}

// Post-nominals that appear in LinkedIn vanity slugs. They are part of the
// slug, not the person, so "damian-walsh-cfp®-chfc®-apma®-71bba819" is Damian
// Walsh. Matched after non-letters are stripped, which also disposes of the ®
// and of the mojibake "â®" that some imported urls carry.
const CREDENTIALS = new Set([
  'cfp', 'cfa', 'cpa', 'chfc', 'clu', 'apma', 'aams', 'crpc', 'cima', 'cpwa',
  'cdfa', 'ricp', 'wmcp', 'caia', 'frm', 'cepa', 'cpfa', 'aif', 'cfe', 'ea',
  'mba', 'bba', 'phd', 'jd', 'md', 'ms', 'ma', 'bs', 'ba', 'msc', 'bsc', 'esq',
  'jr', 'sr', 'ii', 'iii', 'iv', 'cltc', 'chsnc', 'abfp', 'qpfc',
])

// A Unipile/LinkedIn provider id used in place of a vanity slug: "ACoAA…"
// followed by a long opaque body. These reach the CRM lowercased, and they
// split on their underscore into two long gibberish halves — which is exactly
// enough tokens to fool a naive "two or more words is a name" test.
const PROVIDER_ID = /^ac[a-z0-9]a[a-z0-9_-]{12,}$/i

// No surname in this dataset runs past fourteen letters, but every provider-id
// fragment does. One overlong token means the slug is machine-generated.
const MAX_NAME_TOKEN = 14

/** The `{slug}` of a linkedin.com/in/{slug} url, or '' when there isn't one. */
export function linkedinSlug(url: string | null | undefined): string {
  const v = (url || '').trim().replace(/\/+$/, '')
  const i = v.toLowerCase().lastIndexOf('/in/')
  if (i === -1) return ''
  return v.slice(i + 4).split(/[?#]/)[0]
}

/**
 * A person's name recovered from their LinkedIn slug, or null when the slug
 * does not carry one.
 *
 * Most contacts imported from the legacy campaigns have no first/last name, and
 * roughly a third of the CRM is people whose slug is an opaque provider id
 * ("acoaacsy8j8bkmz…"). Guessing a name out of those would be worse than
 * admitting there isn't one, so this insists on at least two alphabetic tokens
 * before it claims to have found a name.
 */
export function nameFromLinkedin(url: string | null | undefined): string | null {
  const slug = linkedinSlug(url)
  if (!slug || PROVIDER_ID.test(slug)) return null
  let decoded = slug
  try {
    decoded = decodeURIComponent(slug)
  } catch {
    // A malformed %-escape is not worth failing over; the raw slug still works.
  }
  const tokens = decoded
    .replace(/_/g, '-')
    .split('-')
    .map((t) => t.replace(/[^a-zA-Z]/g, '').toLowerCase())
    // Drop LinkedIn's uniqueness suffix ("71bba819"), stray digits, and the
    // post-nominals — anything left is a candidate name part.
    .filter((t) => t.length > 1 && !CREDENTIALS.has(t))
  if (tokens.length < 2) return null
  if (tokens.some((t) => t.length > MAX_NAME_TOKEN)) return null
  return tokens.map((t) => t[0].toUpperCase() + t.slice(1)).join(' ')
}

/** Full display name from a lead/message row */
export function fullName(row: NamedRow | null | undefined): string {
  if (!row) return 'Unknown'
  const n = [row.first_name, row.last_name].filter(Boolean).join(' ').trim()
  if (n) return n
  // Never fall through to the bare url. It used to be returned verbatim, which
  // put a 60-character link in the name column of every unnamed contact and
  // fed Avatar an initial of "H" — the h of https — for all of them.
  return nameFromLinkedin(row.linkedin_url) || row.email || 'Unknown'
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
