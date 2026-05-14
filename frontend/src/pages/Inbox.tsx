import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Filter, Sparkles, MessageSquare, Dot, CheckCircle2, Inbox as InboxIcon } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput, Select, Toggle } from '../components/FilterBar'
import ChannelIcon, { CHANNEL_META } from '../components/ChannelIcon'
import { fullName, timeAgo } from '../lib/format'

interface InboxMsg { id: string; first_name?: string; last_name?: string; linkedin_url?: string; email?: string; company?: string; channel: string; occurred_at: string; meta?: { subject?: string; body?: string; message?: string; text?: string; reply_category?: string } }
interface Campaign { id: string; name: string }

export default function Inbox() {
  const [channelFilter, setChannelFilter] = useState('')
  const [campaignFilter, setCampaignFilter] = useState('')
  const [search, setSearch] = useState('')

  const statsQ = useQuery<{ total: number; by_channel: { channel: string; cnt: number }[] }>({ queryKey: ['inbox-stats'], queryFn: () => api.get('/inbox/stats').then(r => r.data) })
  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })

  const params = new URLSearchParams()
  if (channelFilter) params.set('channel', channelFilter)
  if (campaignFilter) params.set('campaign_id', campaignFilter)
  const inboxQ = useQuery<{ messages: InboxMsg[] }>({ queryKey: ['inbox', channelFilter, campaignFilter], queryFn: () => api.get(`/inbox?${params.toString()}`).then(r => r.data) })

  const messages = inboxQ.data?.messages || []
  const visible = search
    ? messages.filter(m => {
        const blob = `${fullName(m)} ${m.company || ''} ${m.meta?.subject || ''} ${m.meta?.body || m.meta?.message || ''}`.toLowerCase()
        return blob.includes(search.toLowerCase())
      })
    : messages

  const byChannel = statsQ.data?.by_channel || []
  const totalInbox = statsQ.data?.total ?? 0

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Inbox"
        eyebrow="Replies"
        title="Unified inbox"
        description="Every inbound reply across LinkedIn, email, WhatsApp, SMS, and voice — one stream."
        actions={
          <>
            <Button variant="secondary" size="md" icon={Filter}>Saved views</Button>
            <Button variant="primary" size="md" icon={Sparkles}>AI summarise</Button>
          </>
        }
        meta={
          totalInbox > 0 && !statsQ.isLoading ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <button
                onClick={() => setChannelFilter('')}
                className={clsx(
                  'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-colors',
                  !channelFilter ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300',
                )}
              >
                All <span className="tabular-nums opacity-70">{totalInbox.toLocaleString()}</span>
              </button>
              {byChannel.map(ch => {
                const meta = CHANNEL_META[ch.channel] || CHANNEL_META.email
                const Ic = meta.icon
                const active = channelFilter === ch.channel
                return (
                  <button
                    key={ch.channel}
                    onClick={() => setChannelFilter(active ? '' : ch.channel)}
                    className={clsx(
                      'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-colors',
                      active ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900' : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300',
                    )}
                  >
                    <Ic size={12} />
                    {meta.label}
                    <span className="tabular-nums opacity-70">{Number(ch.cnt).toLocaleString()}</span>
                  </button>
                )
              })}
            </div>
          ) : null
        }
      />

      <FilterBar>
        <SearchInput placeholder="Search replies, names, companies…" value={search} onChange={setSearch} />
        <Select value={campaignFilter} onChange={setCampaignFilter}>
          <option value="">All campaigns</option>
          {(campaignsQ.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <Toggle
          value="all"
          onChange={() => {}}
          items={[
            { value: 'all', label: 'All', icon: InboxIcon },
            { value: 'unread', label: 'Unread', icon: Dot },
            { value: 'positive', label: 'Positive', icon: CheckCircle2 },
          ]}
        />
      </FilterBar>

      {inboxQ.isLoading ? (
        <div className="space-y-2">{[0,1,2,3].map(i => <div key={i} className="h-20 skeleton rounded-2xl" />)}</div>
      ) : visible.length === 0 ? (
        <Card padding="lg">
          <EmptyState
            icon={MessageSquare}
            title={search ? 'No matches' : 'No replies yet'}
            description={search ? 'Try a different query or clear filters.' : 'Inbound replies will appear here when leads respond to your outreach.'}
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {visible.map(msg => <InboxRow key={msg.id} msg={msg} />)}
        </div>
      )}
    </div>
  )
}

function InboxRow({ msg }: { msg: InboxMsg }) {
  const preview = msg.meta?.body || msg.meta?.message || msg.meta?.text || ''
  const cat = msg.meta?.reply_category
  const catVariant = cat === 'positive' ? 'success' : cat === 'negative' ? 'danger' : 'info'
  return (
    <Card padding="none" className="group cursor-pointer transition-shadow hover:shadow-sm">
      <div className="flex items-start gap-3 p-4">
        <ChannelIcon channel={msg.channel} size="md" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{fullName(msg)}</span>
              {msg.company && <span className="truncate text-xs text-slate-500">at {msg.company}</span>}
              <Badge label={msg.channel} asChannel />
              {cat && <Badge label={cat} variant={catVariant as 'success' | 'danger' | 'info'} dot />}
            </div>
            <span className="flex-shrink-0 text-[11px] tabular-nums text-slate-400">{timeAgo(msg.occurred_at)}</span>
          </div>
          {msg.meta?.subject && (
            <div className="mt-1 truncate text-[13px] font-medium text-slate-600 dark:text-slate-300">{msg.meta.subject}</div>
          )}
          {preview && (
            <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">
              {typeof preview === 'string' ? preview : '—'}
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}
