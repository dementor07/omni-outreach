import { useNavigate } from 'react-router-dom'
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  ListTodo,
  Megaphone,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Send,
  TrendingUp,
  Users,
} from 'lucide-react'

import Badge from '../components/Badge'
import Button from '../components/Button'
import { Card, CardHeader } from '../components/Card'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import { useListCampaigns, type Campaign } from '../hooks/useCampaigns'
import { useQueueStats } from '../hooks/useQueue'
import {
  useDailyActivity,
  useOverviewStats,
  useResponseRates,
  type DailyActivity,
  type ResponseRate,
} from '../hooks/useOverview'

export default function Dashboard() {
  const navigate = useNavigate()
  const campaignsQuery = useListCampaigns()
  const queueStatsQuery = useQueueStats()
  const overviewQuery = useOverviewStats()
  const dailyQuery = useDailyActivity()
  const ratesQuery = useResponseRates()

  const overview = overviewQuery.data
  const campaigns = campaignsQuery.data ?? []
  const queueStats = queueStatsQuery.data ?? []
  const ratesArr = ratesQuery.data ?? []
  const dailyArr = dailyQuery.data ?? []

  const activeCampaigns = campaigns.filter((c) => c.status !== 'archived').length
  const queued = queueStats.filter((r) => r.status === 'queued').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const failed = queueStats.filter((r) => r.status === 'failed').reduce((s, r) => s + Number(r.cnt || 0), 0)

  const refetchAll = () => {
    overviewQuery.refetch()
    ratesQuery.refetch()
    dailyQuery.refetch()
    queueStatsQuery.refetch()
    campaignsQuery.refetch()
  }

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Mission control"
        title="Overview"
        description="Live state of every campaign, channel, and lead in the pipeline."
        actions={
          <>
            <Button variant="secondary" icon={RefreshCw} onClick={refetchAll}>
              Refresh
            </Button>
            <Button variant="primary" icon={Plus} onClick={() => navigate('/campaigns')}>
              New campaign
            </Button>
          </>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total leads"
          value={overviewQuery.isLoading ? '—' : (overview?.total_leads ?? 0)}
          icon={Users}
          accent="brand"
          hint="Across all campaigns"
        />
        <StatCard
          label="Invited"
          value={overviewQuery.isLoading ? '—' : (overview?.invited ?? 0)}
          icon={Send}
          accent="emerald"
        />
        <StatCard
          label="Accepted"
          value={overviewQuery.isLoading ? '—' : (overview?.accepted ?? 0)}
          icon={CheckCircle2}
          accent="amber"
        />
        <StatCard
          label="Messages sent"
          value={overviewQuery.isLoading ? '—' : (overview?.sent ?? 0)}
          icon={Activity}
          accent="brand"
        />
      </section>

      <section className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Active campaigns"
          value={campaignsQuery.isLoading ? '—' : activeCampaigns}
          icon={Megaphone}
          accent="emerald"
        />
        <StatCard
          label="Queued tasks"
          value={queueStatsQuery.isLoading ? '—' : queued}
          icon={ListTodo}
          accent="brand"
        />
        <StatCard
          label="Failed tasks"
          value={queueStatsQuery.isLoading ? '—' : failed}
          icon={AlertCircle}
          accent="rose"
        />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card padding="lg">
          <CardHeader
            title="Daily activity"
            description="Queue executions over the last 14 days"
            actions={<Badge label="live" variant="success" dot />}
          />
          <DailyActivityChart data={dailyArr} loading={dailyQuery.isLoading} />
        </Card>

        <Card padding="lg">
          <CardHeader
            title="Response rates"
            description="Invite → Accept → Reply funnel per campaign"
          />
          {ratesQuery.isLoading ? (
            <div className="space-y-3">
              {[0, 1, 2].map((i) => <div key={i} className="h-14 skeleton rounded-xl" />)}
            </div>
          ) : ratesArr.length === 0 ? (
            <EmptyState icon={TrendingUp} title="No campaign data yet" description="Funnels appear once a campaign has leads." />
          ) : (
            <div className="space-y-3">
              {ratesArr.map((c) => <ResponseRateRow key={c.id} c={c} />)}
            </div>
          )}
        </Card>
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.3fr_0.7fr]">
        <Card padding="lg">
          <CardHeader
            title="Channel breakdown"
            description="Queue performance by channel and state"
            actions={<Button variant="ghost" size="sm" icon={MoreHorizontal} />}
          />
          {queueStatsQuery.isLoading ? (
            <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-10 skeleton rounded-md" />)}</div>
          ) : queueStats.length === 0 ? (
            <EmptyState icon={ListTodo} title="No queue activity" description="Tasks across LinkedIn, email, WhatsApp, and voice will land here." />
          ) : (
            <DataTable
              columns={[
                { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
                { key: 'cnt', header: 'Count', className: 'text-right', render: (row) => (
                  <span className="font-semibold tabular-nums text-slate-900">{Number(row.cnt).toLocaleString()}</span>
                )},
              ]}
              rows={queueStats.map((r, i) => ({ id: `${r.channel}-${r.status}-${i}`, channel: r.channel, status: r.status, cnt: Number(r.cnt || 0) }))}
            />
          )}
        </Card>

        <Card padding="lg">
          <CardHeader title="Campaigns" description="Current state at a glance" />
          {campaignsQuery.isLoading ? (
            <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-20 skeleton rounded-xl" />)}</div>
          ) : campaigns.length === 0 ? (
            <EmptyState
              icon={Megaphone}
              title="No campaigns"
              description="Create one to start the pipeline."
              action={<Button variant="primary" size="sm" icon={Plus} onClick={() => navigate('/campaigns')}>Create campaign</Button>}
            />
          ) : (
            <div className="space-y-2">
              {campaigns.slice(0, 5).map((c) => <CampaignMiniRow key={c.id} c={c} onClick={() => navigate(`/campaigns/${c.id}?tab=leads`)} />)}
            </div>
          )}
        </Card>
      </section>
    </div>
  )
}

interface DailyActivityChartProps {
  data: DailyActivity[]
  loading: boolean
}

function DailyActivityChart({ data, loading }: DailyActivityChartProps) {
  if (loading) return <div className="h-36 skeleton rounded-xl" />
  if (data.length === 0) {
    return <EmptyState icon={BarChart3} title="No activity data" description="The last 14 days of queue executions will plot here." />
  }
  const byDay: Record<string, { sent: number; failed: number; queued: number }> = {}
  data.forEach((r) => {
    const d = (r.day || '').toString().slice(0, 10)
    if (!byDay[d]) byDay[d] = { sent: 0, failed: 0, queued: 0 }
    if (r.status === 'sent') byDay[d].sent += Number(r.cnt)
    else if (r.status === 'failed') byDay[d].failed += Number(r.cnt)
    else byDay[d].queued += Number(r.cnt)
  })
  const days = Object.keys(byDay).sort()
  const max = Math.max(1, ...days.map((d) => byDay[d].sent + byDay[d].failed + byDay[d].queued))
  return (
    <div>
      <div className="flex items-end gap-1.5" style={{ height: 144 }}>
        {days.map((d) => {
          const { sent, failed, queued } = byDay[d]
          const total = sent + failed + queued
          const pct = (total / max) * 100
          return (
            <div key={d} className="group relative flex flex-1 flex-col items-center">
              <div className="flex w-full flex-col overflow-hidden rounded-md" style={{ height: `${pct}%`, minHeight: 4 }}>
                {failed > 0 && <div className="w-full bg-rose-400" style={{ flex: failed }} />}
                {sent > 0 && <div className="w-full bg-emerald-400" style={{ flex: sent }} />}
                {queued > 0 && <div className="w-full bg-brand-300" style={{ flex: queued }} />}
              </div>
              <span className="mt-1.5 text-[10px] tabular-nums text-slate-400">{d.slice(8)}</span>
            </div>
          )
        })}
      </div>
      <div className="mt-3 flex gap-4 text-[11px] text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-400" />Sent</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-rose-400" />Failed</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-brand-300" />Queued</span>
      </div>
    </div>
  )
}

function ResponseRateRow({ c }: { c: ResponseRate }) {
  const acceptRate = c.invited > 0 ? Math.round((c.accepted / c.invited) * 100) : 0
  const replyRate = c.accepted > 0 ? Math.round((c.replied / c.accepted) * 100) : 0
  const rows = [
    { label: 'Accept rate', value: acceptRate, color: 'bg-emerald-400', text: 'text-emerald-600' },
    { label: 'Reply rate', value: replyRate, color: 'bg-brand-500', text: 'text-brand-600' },
  ]
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
      <div className="flex items-center justify-between">
        <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{c.name}</span>
        <span className="text-[11px] text-slate-500">{Number(c.total).toLocaleString()} leads</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-3">
        {rows.map((r) => (
          <div key={r.label}>
            <div className="flex items-center justify-between text-[11px]">
              <span className="text-slate-500">{r.label}</span>
              <span className={`font-semibold tabular-nums ${r.text}`}>{r.value}%</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div className={`h-full rounded-full transition-all ${r.color}`} style={{ width: `${r.value}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function CampaignMiniRow({ c, onClick }: { c: Campaign; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="block w-full rounded-xl border border-slate-200 bg-slate-50/40 p-3 text-left transition-colors hover:bg-slate-100/60 dark:border-slate-800 dark:bg-slate-800/30 dark:hover:bg-slate-800/60"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{c.name}</p>
          <p className="mt-0.5 text-[11px] uppercase tracking-[0.12em] text-slate-400">{c.timezone || '—'}</p>
        </div>
        <Badge
          label={c.simulation_mode ? 'simulation' : (c.status || 'live')}
          asStatus
          dot
        />
      </div>
      <div className="mt-2 flex items-center gap-3 text-[11px] text-slate-500">
        <span>Daily cap <span className="font-semibold tabular-nums text-slate-900 dark:text-slate-200">{c.daily_lead_cap ?? '—'}</span></span>
        <span className="h-3 w-px bg-slate-200" />
        <span>Invite cap <span className="font-semibold tabular-nums text-slate-900 dark:text-slate-200">{c.invite_daily_cap ?? '—'}</span></span>
      </div>
    </button>
  )
}
