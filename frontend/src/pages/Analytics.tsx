import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users, Send, CheckCircle2, MessageSquare, BarChart3, Activity as ActivityIcon } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card, { CardHeader } from '../components/Card'
import EmptyState from '../components/EmptyState'
import ChannelIcon, { CHANNEL_META } from '../components/ChannelIcon'
import { Select } from '../components/FilterBar'

interface Campaign { id: string; name: string }
interface AnalyticsData {
  funnel: { total_leads: number; invited: number; accepted: number; replied: number }
  rates: { accept_rate: number; reply_rate: number }
  channel_breakdown: { channel: string; cnt: number }[]
  daily_activity: { events: number }[]
}

export default function Analytics() {
  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const [campaignId, setCampaignId] = useState('')

  useEffect(() => {
    if (!campaignId && campaignsQ.data?.length) setCampaignId(campaignsQ.data[0].id)
  }, [campaignsQ.data, campaignId])

  const analyticsQ = useQuery<AnalyticsData>({
    queryKey: ['analytics', campaignId],
    queryFn: () => api.get(`/analytics/${campaignId}`).then(r => r.data),
    enabled: !!campaignId,
  })

  const data = analyticsQ.data
  const funnel = data?.funnel || { total_leads: 0, invited: 0, accepted: 0, replied: 0 }
  const rates = data?.rates || { accept_rate: 0, reply_rate: 0 }
  const channels = data?.channel_breakdown || []
  const daily = data?.daily_activity || []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Analytics"
        eyebrow="Insights"
        title="Campaign analytics"
        description="Funnel, conversion rates, channel mix, and 30-day activity for the selected campaign."
        actions={
          <Select value={campaignId} onChange={setCampaignId}>
            {(campaignsQ.data || []).length === 0 && <option value="">No campaigns</option>}
            {(campaignsQ.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        }
      />

      {!campaignId ? (
        <Card padding="lg"><EmptyState icon={BarChart3} title="Choose a campaign" description="Select a campaign to load analytics." /></Card>
      ) : analyticsQ.isLoading ? (
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[0,1,2,3].map(i => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
          <div className="h-64 skeleton rounded-2xl" />
        </div>
      ) : (
        <>
          <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Total leads" value={funnel.total_leads} icon={Users} accent="brand" />
            <StatCard label="Invited" value={funnel.invited} icon={Send} accent="emerald" />
            <StatCard label="Accepted" value={funnel.accepted} icon={CheckCircle2} accent="amber" hint={`${rates.accept_rate ?? 0}% accept rate`} />
            <StatCard label="Replied" value={funnel.replied} icon={MessageSquare} accent="violet" hint={`${rates.reply_rate ?? 0}% reply rate`} />
          </section>

          <section className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
            <Card padding="lg">
              <CardHeader title="Funnel" description="Invite → Accept → Reply" />
              <Funnel funnel={funnel} rates={rates} />
            </Card>
            <Card padding="lg">
              <CardHeader title="Channel mix" description="Events by channel" />
              {channels.length === 0 ? (
                <EmptyState icon={ActivityIcon} title="No events" description="Channel mix will appear once events fire." />
              ) : (
                <div className="space-y-2.5">
                  {channels.map(row => <ChannelBar key={row.channel} channel={row.channel} value={Number(row.cnt)} max={Math.max(...channels.map(c => Number(c.cnt)))} />)}
                </div>
              )}
            </Card>
          </section>

          <Card padding="lg">
            <CardHeader title="Daily activity" description="Events over the last 30 days" />
            <DailyActivity30 rows={daily} />
          </Card>
        </>
      )}
    </div>
  )
}

function Funnel({ funnel, rates }: { funnel: AnalyticsData['funnel']; rates: AnalyticsData['rates'] }) {
  const t = funnel.total_leads, i = funnel.invited, a = funnel.accepted, r = funnel.replied
  const max = Math.max(1, t, i, a, r)
  const rows = [
    { label: 'Total Leads', value: t, color: 'bg-slate-200 dark:bg-slate-700', pct: undefined as number | undefined },
    { label: 'Invited', value: i, color: 'bg-brand-500', pct: t ? Math.round((i / t) * 100) : 0 },
    { label: 'Accepted', value: a, color: 'bg-emerald-500', pct: rates.accept_rate },
    { label: 'Replied', value: r, color: 'bg-violet-500', pct: rates.reply_rate },
  ]
  return (
    <div className="space-y-5">
      {rows.map(row => (
        <div key={row.label} className="group">
          <div className="flex items-center justify-between text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">
            <span>{row.label}</span>
            <div className="flex items-center gap-2">
              <span className="text-slate-900 dark:text-white tabular-nums">{row.value.toLocaleString()}</span>
              {row.pct != null && (
                <span className="rounded bg-slate-50 px-1.5 py-0.5 text-[10px] text-slate-500 dark:bg-slate-800/50">
                  {row.pct}%
                </span>
              )}
            </div>
          </div>
          <div className="relative h-2.5 overflow-hidden rounded-full bg-slate-50 dark:bg-slate-800/50">
            <div 
              className={clsx('h-full rounded-full transition-all duration-700 ease-out', row.color)} 
              style={{ width: `${(row.value / max) * 100}%` }} 
            />
          </div>
        </div>
      ))}
    </div>
  )
}

function ChannelBar({ channel, value, max }: { channel: string; value: number; max: number }) {
  const meta = CHANNEL_META[channel] || CHANNEL_META.email
  const pct = max ? Math.round((value / max) * 100) : 0
  return (
    <div className="flex items-center gap-4 group">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-50 dark:bg-slate-800/50 text-slate-400 group-hover:text-brand-500 transition-colors">
        <ChannelIcon channel={channel} size={14} />
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between text-[11px] font-bold text-slate-700 dark:text-slate-300 mb-1.5">
          <span>{meta.label}</span>
          <span className="tabular-nums">{value.toLocaleString()}</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-50 dark:bg-slate-800/50">
          <div 
            className="h-full rounded-full bg-brand-500 transition-all duration-500" 
            style={{ width: `${pct}%` }} 
          />
        </div>
      </div>
    </div>
  )
}

function DailyActivity30({ rows }: { rows: { events: number }[] }) {
  if (!rows || rows.length === 0) return <EmptyState icon={BarChart3} title="No events" description="A 30-day chart will appear once events fire." />
  const max = Math.max(1, ...rows.map(r => Number(r.events)))
  return (
    <div className="flex items-end gap-1 px-1" style={{ height: 180 }}>
      {rows.map((r, i) => {
        const v = Number(r.events)
        const pct = (v / max) * 100
        return (
          <div key={i} className="group relative flex flex-1 flex-col items-center h-full justify-end">
            <div 
              className="w-full rounded-t-sm bg-brand-500/20 group-hover:bg-brand-500 transition-all duration-300" 
              style={{ height: `${Math.max(2, pct)}%` }} 
              title={`${v} events`}
            />
            {/* Tooltip on hover */}
            <div className="absolute -top-8 left-1/2 -translate-x-1/2 opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity bg-slate-900 text-white text-[10px] px-2 py-1 rounded shadow-xl whitespace-nowrap z-10">
              {v} events
            </div>
          </div>
        )
      })}
    </div>
  )
}
