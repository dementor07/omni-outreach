import { useMemo, useState } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Inbox as InboxIcon, MessageSquare, Dot, CheckCircle2, ChevronLeft, Sparkles, Send, UserPlus, Pencil } from 'lucide-react'
import { inbox, canvas, type InboxThread } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Avatar from '../components/Avatar'
import EmptyState from '../components/EmptyState'
import ChannelIcon, { CHANNEL_META } from '../components/ChannelIcon'
import { FilterBar, SearchInput, Select, Toggle } from '../components/FilterBar'
import { useToast } from '../components/Toast'
import { timeAgo } from '../lib/format'

type ClassFilter = 'all' | 'positive' | 'objection' | 'unsubscribe'

export default function Inbox() {
  const { contactId } = useParams<{ contactId?: string }>()
  const navigate = useNavigate()
  const [campaignFilter, setCampaignFilter] = useState('')
  const threadsQ = useQuery({
    queryKey: ['inbox-threads', campaignFilter],
    queryFn: () => inbox.threads(200, campaignFilter || undefined),
  })
  const threadQ = useQuery({
    queryKey: ['inbox-thread', contactId],
    queryFn: () => inbox.thread(contactId!),
    enabled: !!contactId,
    // The thread fetches the live Unipile chat — cache it so re-opening the same
    // thread doesn't re-hit Unipile on every navigation/focus (usage-conscious).
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  })
  const campaignsQ = useQuery({ queryKey: ['workflows-list'], queryFn: () => canvas.list() })

  const [channelFilter, setChannelFilter] = useState('')
  const [search, setSearch] = useState('')
  const [classFilter, setClassFilter] = useState<ClassFilter>('all')

  const threads = useMemo(() => threadsQ.data ?? [], [threadsQ.data])
  const byChannel = useMemo(() => groupByChannel(threads), [threads])
  const totalThreads = threads.length

  const visible = useMemo(() => {
    let out = threads
    if (channelFilter) out = out.filter((t) => t.last_channel === channelFilter)
    if (classFilter !== 'all') out = out.filter((t) => t.last_classification === classFilter)
    if (search) {
      const q = search.toLowerCase()
      out = out.filter((t) => (t.last_snippet ?? '').toLowerCase().includes(q) || contactName(t).toLowerCase().includes(q))
    }
    return out
  }, [threads, channelFilter, classFilter, search])

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Inbox"
        eyebrow="Replies"
        title="Unified inbox"
        description="Every inbound and outbound message across email, LinkedIn, SMS, voice — one projection."
        meta={
          totalThreads > 0 && !threadsQ.isLoading ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                type="button"
                onClick={() => setChannelFilter('')}
                className={clsx(
                  'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-colors',
                  !channelFilter
                    ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300',
                )}
              >
                All <span className="tabular-nums opacity-70">{totalThreads.toLocaleString()}</span>
              </button>
              {byChannel.map(({ channel, count }) => {
                const meta = CHANNEL_META[channel] ?? CHANNEL_META.email
                const Ic = meta.icon
                const active = channelFilter === channel
                return (
                  <button
                    key={channel}
                    type="button"
                    onClick={() => setChannelFilter(active ? '' : channel)}
                    className={clsx(
                      'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-colors',
                      active
                        ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                        : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300',
                    )}
                  >
                    <Ic size={12} />
                    {channelLabel(channel, meta.label)}
                    <span className="tabular-nums opacity-70">{count.toLocaleString()}</span>
                  </button>
                )
              })}
            </div>
          ) : null
        }
      />

      <FilterBar>
        <SearchInput placeholder="Search by name or message…" value={search} onChange={setSearch} />
        <Select
          value={campaignFilter}
          onChange={setCampaignFilter}
          className="min-w-44"
        >
          <option value="">All campaigns</option>
          {(campaignsQ.data ?? []).map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </Select>
        <Toggle
          value={classFilter}
          onChange={(v) => setClassFilter(v as ClassFilter)}
          items={[
            { value: 'all', label: 'All', icon: InboxIcon },
            { value: 'positive', label: 'Positive', icon: CheckCircle2 },
            { value: 'objection', label: 'Objection', icon: Dot },
            { value: 'unsubscribe', label: 'Unsubscribe', icon: Dot },
          ]}
        />
      </FilterBar>

      {threadsQ.isLoading ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-20 skeleton rounded-2xl" />)}</div>
      ) : visible.length === 0 ? (
        <Card padding="lg">
          <EmptyState
            icon={MessageSquare}
            title={search ? 'No matches' : 'No replies yet'}
            description={search ? 'Try a different query or clear filters.' : 'Inbound replies will appear here when contacts respond to your outreach.'}
          />
        </Card>
      ) : contactId ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[360px_1fr]">
          <ThreadList threads={visible} activeId={contactId} />
          <ThreadPane
            contactId={contactId}
            name={(() => {
              const a = threads.find((t) => t.contact_id === contactId)
              return a ? contactName(a) : `Contact ${contactId.slice(0, 8)}`
            })()}
            messages={threadQ.data ?? []}
            loading={threadQ.isLoading}
            lastChannel={threads.find((t) => t.contact_id === contactId)?.last_channel ?? null}
            onBack={() => navigate('/inbox')}
          />
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map((t) => (
            <ThreadRow key={t.contact_id} thread={t} />
          ))}
        </div>
      )}
    </div>
  )
}

function groupByChannel(threads: InboxThread[]): { channel: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const t of threads) {
    if (!t.last_channel) continue
    counts.set(t.last_channel, (counts.get(t.last_channel) ?? 0) + 1)
  }
  return Array.from(counts.entries())
    .map(([channel, count]) => ({ channel, count }))
    .sort((a, b) => b.count - a.count)
}

function channelLabel(channel: string, fallback: string): string {
  const normalized = channel.toLowerCase().replace(/[._-]+/g, ' ')
  if (normalized.includes('linkedin') && normalized.includes('invite')) return 'Invites'
  if (normalized.includes('linkedin') && (normalized.includes('dm') || normalized.includes('message'))) return 'DMs'
  if (normalized.includes('whatsapp')) return 'WhatsApp'
  if (normalized.includes('sms')) return 'SMS'
  return fallback
}

// Resolve a human name for a thread — falls back to company, then a short id.
// (The old UI rendered the raw contact_id, which read like a "lead id".)
function contactName(t: Pick<InboxThread, 'first_name' | 'last_name' | 'company' | 'contact_id'>): string {
  const full = [t.first_name, t.last_name].filter(Boolean).join(' ').trim()
  if (full) return full
  if (t.company) return t.company
  return `Contact ${t.contact_id.slice(0, 8)}`
}

// ── Row layout (no thread selected) ──────────────────────────────────────────
function ThreadRow({ thread }: { thread: InboxThread }) {
  const cls = thread.last_classification
  const variant: 'success' | 'danger' | 'info' | 'neutral' =
    cls === 'positive' ? 'success' : cls === 'unsubscribe' ? 'danger' : cls === 'objection' ? 'info' : 'neutral'
  const channel = thread.last_channel ?? 'email'
  const name = contactName(thread)
  return (
    <Link to={`/inbox/${thread.contact_id}`} className="block">
      <Card padding="none" hover className="group cursor-pointer">
        <div className="flex items-start gap-3 p-3.5 sm:p-4">
          <Avatar name={name} size={36} />
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{name}</span>
                {thread.company && <span className="truncate text-xs text-slate-400">{thread.company}</span>}
                <Badge label={channel} asChannel />
                {thread.inbound_count > 0 ? (
                  <Badge label="Replied" variant="success" dot />
                ) : (
                  cls && <Badge label={cls} variant={variant} dot />
                )}
              </div>
              <span className="flex-shrink-0 text-[11px] tabular-nums text-slate-400">
                {timeAgo(thread.last_message_at)}
              </span>
            </div>
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">
              {thread.last_snippet ?? (thread.inbound_count > 0 ? 'Replied' : `${thread.sent_count} sent · no reply yet`)}
            </p>
          </div>
        </div>
      </Card>
    </Link>
  )
}

// ── Thread list (left side when one is selected) ─────────────────────────────
function ThreadList({ threads, activeId }: { threads: InboxThread[]; activeId: string }) {
  return (
    <Card padding="none" className="max-h-[640px] overflow-y-auto">
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {threads.map((t) => {
          const channel = t.last_channel ?? 'email'
          const cls = t.last_classification
          const variant: 'success' | 'danger' | 'info' | 'neutral' =
            cls === 'positive' ? 'success' : cls === 'unsubscribe' ? 'danger' : cls === 'objection' ? 'info' : 'neutral'
          const isActive = activeId === t.contact_id
          const name = contactName(t)
          return (
            <li key={t.contact_id}>
              <Link
                to={`/inbox/${t.contact_id}`}
                className={clsx(
                  'flex items-start gap-3 px-3 py-3 hover:bg-slate-50 dark:hover:bg-slate-900/50',
                  isActive && 'bg-brand-50 dark:bg-brand-900/20',
                )}
              >
                <Avatar name={name} size={32} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{name}</p>
                    <span className="text-[10px] tabular-nums text-slate-400">{timeAgo(t.last_message_at)}</span>
                  </div>
                  <p className="mt-0.5 truncate text-xs text-slate-500">
                    {t.last_snippet ?? (t.inbound_count > 0 ? 'Replied' : `${t.sent_count} sent`)}
                  </p>
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <Badge label={channel} asChannel size="xs" />
                    {t.inbound_count > 0 ? (
                      <Badge label="Replied" variant="success" size="xs" dot />
                    ) : (
                      cls && <Badge label={cls} variant={variant} size="xs" dot />
                    )}
                    <span className="text-[10px] text-slate-400">{t.message_count} msgs</span>
                  </div>
                </div>
              </Link>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

// ── Thread pane (right side) ─────────────────────────────────────────────────
function ThreadPane({
  contactId,
  name,
  messages,
  loading,
  lastChannel,
  onBack,
}: {
  contactId: string
  name: string
  messages: import('../api/v2').InboxMessage[]
  loading: boolean
  lastChannel: string | null
  onBack: () => void
}) {
  return (
    <Card padding="none" className="flex max-h-[640px] flex-col">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            title="Back to thread list"
            aria-label="Back to thread list"
            className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 lg:hidden"
          >
            <ChevronLeft size={16} />
          </button>
          <Avatar name={name} size={32} />
          <div>
            <Link to={`/contacts/${contactId}`} className="text-sm font-semibold text-slate-900 hover:underline dark:text-white">{name}</Link>
            <p className="text-[11px] text-slate-500">{messages.length} messages</p>
          </div>
        </div>
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {loading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : messages.length === 0 ? (
          <EmptyState title="No messages" description="Nothing yet on this thread." />
        ) : (
          messages.map((m) => <MessageBubble key={m.id} m={m} contactId={contactId} />)
        )}
      </div>
      <ReplyComposer contactId={contactId} channel={lastChannel} />
    </Card>
  )
}

// ── Reply composer (B3): AI-suggested draft + DNC-checked send ───────────────
function ReplyComposer({ contactId, channel }: { contactId: string; channel: string | null }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState('')
  const [source, setSource] = useState<string | null>(null)

  const suggestMut = useMutation({
    mutationFn: () => inbox.suggest(contactId),
    onSuccess: (res) => {
      setDraft(res.draft)
      setSource(res.source)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not draft a reply'),
  })

  const sendMut = useMutation({
    mutationFn: () => inbox.reply(contactId, { body: draft.trim(), channel: channel ?? undefined }),
    onSuccess: (res) => {
      setDraft('')
      setSource(null)
      toast.success(`Reply queued on ${res.channel}`)
      qc.invalidateQueries({ queryKey: ['inbox-thread', contactId] })
      qc.invalidateQueries({ queryKey: ['inbox-threads'] })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not send reply'),
  })

  const channelLabel = channel ? (CHANNEL_META[channel]?.label ?? channel) : 'channel'

  return (
    <div className="border-t border-slate-100 p-3 dark:border-slate-800">
      <textarea
        value={draft}
        onChange={(e) => { setDraft(e.target.value); if (source) setSource(null) }}
        rows={3}
        placeholder={`Write a reply on ${channelLabel}…`}
        className="w-full resize-none rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-brand-900/40"
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => suggestMut.mutate()}
            disabled={suggestMut.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            <Sparkles size={13} />
            {suggestMut.isPending ? 'Drafting…' : 'AI suggest'}
          </button>
          {source && (
            <span className="text-[11px] text-slate-400">
              {source === 'llm' ? 'AI draft — review before sending' : 'Template draft — personalize it'}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => sendMut.mutate()}
          disabled={!draft.trim() || sendMut.isPending}
          className="inline-flex items-center gap-1.5 rounded-md bg-brand-500 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Send size={13} />
          {sendMut.isPending ? 'Sending…' : 'Send'}
        </button>
      </div>
    </div>
  )
}

/**
 * MSG-EDIT-002 — really edit a sent message on LinkedIn.
 *
 * This is a live outbound action: the recipient sees the new text. LinkedIn only
 * allows it for a limited period after sending, and refuses afterwards — the
 * provider's reason is surfaced verbatim rather than a generic failure. The text
 * before the edit is kept locally (LinkedIn keeps no history) so the thread can
 * still show what was originally sent.
 */
function MessageBubble({ m, contactId }: { m: import('../api/v2').InboxMessage; contactId: string }) {
  const outbound = m.direction === 'outbound'
  const meta = m.metadata as
    | {
        system?: boolean; kind?: string; edited?: boolean; original_body?: string
        edit_reason?: string | null; edited_at?: string
        provider_message_id?: string; account_id?: string
      }
    | null
    | undefined
  // Only your own message, and only one the provider can still address, is editable.
  const canEdit = outbound && Boolean(meta?.provider_message_id && meta?.account_id)
  const qc = useQueryClient()
  const toast = useToast()
  const [editing, setEditing] = useState(false)
  const [showOriginal, setShowOriginal] = useState(false)
  const [text, setText] = useState(m.body ?? '')
  const [reason, setReason] = useState('')

  const refresh = () => qc.invalidateQueries({ queryKey: ['inbox-thread', contactId] })

  const saveMut = useMutation({
    mutationFn: () => inbox.editMessage(contactId, m.id, { body: text.trim(), reason: reason.trim() || undefined }),
    onSuccess: () => { setEditing(false); setReason(''); refresh(); toast.success('Edited on LinkedIn') },
    // The provider's own reason (usually "the edit window has closed") is the
    // useful part — show it instead of a generic failure.
    onError: (err) => toast.error(err instanceof Error ? err.message : 'LinkedIn refused the edit'),
  })
  const revertMut = useMutation({
    mutationFn: () => inbox.revertMessage(contactId, m.id),
    onSuccess: (r) => { setText(r.body); setShowOriginal(false); refresh(); toast.success('Put back to the original') },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'LinkedIn refused the edit'),
  })

  if (meta?.system) {
    // A connection/invite event (not a chat message) — a distinct, centered pill.
    const isInvite = meta.kind === 'invite'
    return (
      <div className="flex justify-center">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-400">
          {isInvite ? <UserPlus size={12} className="text-brand-500" /> : <ChannelIcon channel={m.channel} size="sm" />}
          {m.body} · {new Date(m.occurred_at).toLocaleString()}
        </span>
      </div>
    )
  }
  return (
    <div className={clsx('flex items-start gap-2', outbound ? 'justify-end' : 'justify-start')}>
      {!outbound && <ChannelIcon channel={m.channel} size="sm" />}
      <div
        className={clsx(
          'max-w-[80%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed shadow-sm',
          outbound
            ? 'bg-brand-500 text-white'
            : 'border border-slate-200 bg-white text-slate-900 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100',
        )}
      >
        {m.subject && <p className={clsx('mb-1 text-xs font-semibold', outbound ? 'opacity-90' : 'text-slate-500')}>{m.subject}</p>}

        {editing ? (
          <div className="space-y-2">
            <textarea
              autoFocus
              rows={4}
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="w-full resize-y rounded-lg border border-white/40 bg-white/95 px-2.5 py-2 text-sm text-slate-900 outline-none dark:bg-slate-950 dark:text-slate-100"
            />
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Note for your records (optional)"
              className="w-full rounded-lg border border-white/40 bg-white/95 px-2.5 py-1.5 text-[11px] text-slate-700 outline-none dark:bg-slate-950 dark:text-slate-200"
            />
            <p className={clsx('text-[10px] leading-snug', outbound ? 'text-white/75' : 'text-slate-500')}>
              This edits the message on LinkedIn — they'll see the new text, marked edited.
              Only possible for a short window after sending.
            </p>
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => { setEditing(false); setText(m.body ?? '') }}
                className={clsx('text-[11px] font-semibold', outbound ? 'text-white/80' : 'text-slate-500')}
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={saveMut.isPending || !text.trim() || text.trim() === (m.body ?? '')}
                onClick={() => saveMut.mutate()}
                className="rounded-lg bg-white px-2.5 py-1 text-[11px] font-bold text-brand-700 disabled:opacity-40 dark:bg-slate-800 dark:text-brand-200"
              >
                {saveMut.isPending ? 'Editing…' : 'Edit on LinkedIn'}
              </button>
            </div>
          </div>
        ) : (
          <p className="whitespace-pre-wrap">{m.body ?? ''}</p>
        )}

        {meta?.edited && !editing && (
          <div className={clsx('mt-1.5 rounded-lg px-2 py-1.5 text-[10px]', outbound ? 'bg-white/15' : 'bg-amber-50 dark:bg-amber-950/30')}>
            <span className={clsx('font-bold uppercase tracking-wide', outbound ? 'text-white/90' : 'text-amber-700 dark:text-amber-300')}>
              Edited
            </span>
            {meta.edit_reason && <span className={outbound ? 'text-white/80' : 'text-amber-700 dark:text-amber-300'}> · {meta.edit_reason}</span>}
            {meta.edited_at && (
              <span className={clsx('ml-1', outbound ? 'text-white/70' : 'text-amber-600 dark:text-amber-400')}>
                · {new Date(meta.edited_at).toLocaleString()}
              </span>
            )}
            <div className="mt-1 flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowOriginal((v) => !v)}
                className={clsx('font-semibold underline', outbound ? 'text-white/90' : 'text-amber-800 dark:text-amber-200')}
              >
                {showOriginal ? 'Hide what was sent' : 'What was originally sent'}
              </button>
              <button
                type="button"
                disabled={revertMut.isPending}
                onClick={() => revertMut.mutate()}
                className={clsx('font-semibold underline disabled:opacity-40', outbound ? 'text-white/90' : 'text-amber-800 dark:text-amber-200')}
              >
                {revertMut.isPending ? 'Putting back…' : 'Put back'}
              </button>
            </div>
            {showOriginal && (
              <p className={clsx('mt-1.5 whitespace-pre-wrap border-t pt-1.5', outbound ? 'border-white/25 text-white/85' : 'border-amber-200 text-amber-900 dark:border-amber-900 dark:text-amber-100')}>
                {meta.original_body}
              </p>
            )}
          </div>
        )}

        <p className={clsx('mt-1.5 flex items-center gap-1.5 text-[10px]', outbound ? 'opacity-70' : 'text-slate-400')}>
          <span>{m.channel} · {new Date(m.occurred_at).toLocaleString()}</span>
          {m.classification && <span>· {m.classification}</span>}
          {!editing && canEdit && (
            <button
              type="button"
              onClick={() => { setText(m.body ?? ''); setEditing(true) }}
              className="ml-auto inline-flex items-center gap-1 font-semibold underline"
              aria-label="Edit this message on LinkedIn"
              title="Edit on LinkedIn — only possible for a short window after sending"
            >
              <Pencil size={9} /> Edit
            </button>
          )}
        </p>
      </div>
      {outbound && <ChannelIcon channel={m.channel} size="sm" />}
    </div>
  )
}
