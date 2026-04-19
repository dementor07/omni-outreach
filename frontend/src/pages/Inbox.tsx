import { useState } from 'react'
import { Inbox as InboxIcon, Mail, Linkedin, MessageSquare, Phone, Filter, User } from 'lucide-react'
import { useInbox, useInboxStats } from '../hooks/useInbox'
import { useListCampaigns } from '../hooks/useCampaigns'
import EmptyState from '../components/EmptyState'
import Badge from '../components/Badge'

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

const CHANNEL_CONFIG: Record<string, { icon: typeof Mail; color: string; bg: string }> = {
  email: { icon: Mail, color: 'text-sky-600', bg: 'bg-sky-100' },
  linkedin: { icon: Linkedin, color: 'text-blue-600', bg: 'bg-blue-100' },
  whatsapp: { icon: MessageSquare, color: 'text-emerald-600', bg: 'bg-emerald-100' },
  sms: { icon: Phone, color: 'text-violet-600', bg: 'bg-violet-100' },
}

export default function Inbox() {
  const [channelFilter, setChannelFilter] = useState('')
  const [campaignFilter, setCampaignFilter] = useState('')
  const [page, setPage] = useState(1)

  const { data, isLoading } = useInbox(channelFilter || undefined, campaignFilter || undefined, undefined, page)
  const stats = useInboxStats()
  const campaigns = useListCampaigns()

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Unified Inbox</h1>
          <p className="mt-1 text-sm text-slate-500">
            All inbound replies across channels
            {stats.data && <span className="ml-2 font-semibold text-sky-600">· {stats.data.total} total</span>}
          </p>
        </div>
      </div>

      {/* Channel stats chips */}
      {stats.data && stats.data.by_channel.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {stats.data.by_channel.map((ch) => {
            const cfg = CHANNEL_CONFIG[ch.channel] || CHANNEL_CONFIG.email
            const Icon = cfg.icon
            return (
              <button
                key={ch.channel}
                onClick={() => setChannelFilter(channelFilter === ch.channel ? '' : ch.channel)}
                className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-colors ${channelFilter === ch.channel ? 'border-sky-300 bg-sky-50 text-sky-700' : 'border-slate-200 text-slate-600 hover:bg-slate-50'}`}
              >
                <Icon size={13} />
                <span className="capitalize">{ch.channel}</span>
                <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold">{ch.cnt}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
        <select
          value={campaignFilter}
          onChange={(e) => { setCampaignFilter(e.target.value); setPage(1) }}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none"
        >
          <option value="">All campaigns</option>
          {(campaigns.data || []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* Message list */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3, 4].map((i) => <div key={i} className="h-20 animate-pulse rounded-xl bg-slate-100" />)}
        </div>
      ) : !data?.messages.length ? (
        <EmptyState icon={MessageSquare} title="No messages yet" description="Inbound replies will appear here when leads respond to your outreach." />
      ) : (
        <div className="space-y-2">
          {data.messages.map((msg) => {
            const cfg = CHANNEL_CONFIG[msg.channel] || CHANNEL_CONFIG.email
            const Icon = cfg.icon
            const name = [msg.first_name, msg.last_name].filter(Boolean).join(' ') || 'Unknown'
            const preview = msg.meta?.body || msg.meta?.message || msg.meta?.text || JSON.stringify(msg.meta)

            return (
              <div key={msg.id} className="rounded-xl border border-slate-200 bg-white p-4 transition-shadow hover:shadow-sm">
                <div className="flex items-start gap-3">
                  <div className={`flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full ${cfg.bg}`}>
                    <Icon size={16} className={cfg.color} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900">{name}</span>
                        {msg.company && <span className="text-xs text-slate-400">at {msg.company}</span>}
                        <Badge label={msg.channel} asChannel />
                      </div>
                      <span className="flex-shrink-0 text-xs text-slate-400">{timeAgo(msg.occurred_at)}</span>
                    </div>
                    {msg.meta?.subject && (
                      <div className="mt-1 text-xs font-medium text-slate-600">{msg.meta.subject}</div>
                    )}
                    <p className="mt-1 line-clamp-2 text-sm text-slate-600 leading-relaxed">
                      {typeof preview === 'string' ? preview : '—'}
                    </p>
                    {msg.meta?.reply_category && (
                      <div className="mt-2">
                        <Badge
                          label={msg.meta.reply_category}
                          variant={
                            msg.meta.reply_category === 'positive' ? 'success' :
                            msg.meta.reply_category === 'negative' ? 'error' :
                            'info'
                          }
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {data && data.total > 30 && (
        <div className="flex justify-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <span className="flex items-center px-3 text-sm text-slate-500">
            Page {page} of {Math.ceil(data.total / 30)}
          </span>
          <button
            disabled={page >= Math.ceil(data.total / 30)}
            onClick={() => setPage(page + 1)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
