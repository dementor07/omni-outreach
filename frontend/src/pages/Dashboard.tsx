import { Activity, CheckCircle2, ListTodo, Megaphone, Send, Users, TrendingUp } from 'lucide-react'
import { Link } from 'react-router-dom'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import StatCard from '../components/StatCard'
import { useListCampaigns } from '../hooks/useCampaigns'
import { useQueueStats } from '../hooks/useQueue'
import { useOverviewStats, useDailyActivity, useResponseRates } from '../hooks/useOverview'
import { formatRelative, formatScheduled } from '../lib/time'

export default function Dashboard() {
  const campaignsQuery = useListCampaigns()
  const queueStatsQuery = useQueueStats()
  const overviewQuery = useOverviewStats()
  const dailyQuery = useDailyActivity()
  const ratesQuery = useResponseRates()

  const campaigns = campaignsQuery.data || []
  const queueStats = queueStatsQuery.data || []
  const overview = overviewQuery.data

  // Falls back to queue stats if overview endpoint not yet available
  const totalLeads = overview?.total_leads ?? 0
  const invited = overview?.invited ?? queueStats
    .filter((r) => r.channel === 'linkedin_invite' && r.status === 'sent')
    .reduce((s, r) => s + Number(r.cnt || 0), 0)
  const accepted = overview?.accepted ?? queueStats
    .filter((r) => r.channel === 'linkedin_dm' && r.status === 'sent')
    .reduce((s, r) => s + Number(r.cnt || 0), 0)
  const sentTotal = overview?.sent ?? queueStats
    .filter((r) => r.status === 'sent')
    .reduce((s, r) => s + Number(r.cnt || 0), 0)

  const activeCampaigns = campaigns.filter((c) => c.status !== 'archived').length
  const queuedTasks = queueStats.filter((r) => r.status === 'queued').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const failedTasks = queueStats.filter((r) => r.status === 'failed').reduce((s, r) => s + Number(r.cnt || 0), 0)

  const breakdownRows = queueStats.map((row, i) => ({
    id: `${row.channel}-${row.status}-${i}`,
    channel: row.channel,
    status: row.status,
    count: Number(row.cnt || 0),
  }))

  const isFirstRun = !campaignsQuery.isLoading && campaigns.length === 0

  const loading = campaignsQuery.isLoading || queueStatsQuery.isLoading

  return (
    <div className="space-y-8">
      {/* Hero */}
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Overview</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              Mission control for outreach operations
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Monitor queue pressure, campaign load, and channel delivery from one place.
            </p>
          </div>
          <div className="shrink-0 rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-sm text-slate-600">
            <div className="font-medium text-slate-900">Live data</div>
            <div className="mt-1 text-slate-400">Refreshes every 30 seconds</div>
          </div>
        </div>
      </section>

      {/* First-run onboarding */}
      {isFirstRun && (
        <section className="rounded-3xl border border-sky-200 bg-sky-50 p-8">
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-600">Get started</p>
          <h2 className="mt-2 text-xl font-semibold text-slate-900">No campaigns yet</h2>
          <p className="mt-2 text-sm text-slate-500">
            Create a campaign, configure your sequence steps, and import leads to start the pipeline.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              to="/campaigns"
              className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-600 transition-colors"
            >
              <Megaphone size={15} />
              Create first campaign
            </Link>
            <Link
              to="/settings"
              className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
            >
              Connect LinkedIn account
            </Link>
          </div>
        </section>
      )}

      {/* Stat cards row 1 */}
      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total Leads" value={totalLeads} icon={Users} accent="sky" loading={loading} />
        <StatCard label="Invites Sent" value={invited} icon={Send} accent="emerald" loading={loading} />
        <StatCard label="Accepted" value={accepted} icon={CheckCircle2} accent="amber" loading={loading} />
        <StatCard label="Messages Sent" value={sentTotal} icon={Activity} accent="sky" loading={loading} />
      </section>

      {/* Stat cards row 2 */}
      <section className="grid gap-4 md:grid-cols-3">
        <StatCard label="Active Campaigns" value={activeCampaigns} icon={Megaphone} accent="emerald" loading={campaignsQuery.isLoading} />
        <StatCard label="Queued Tasks" value={queuedTasks} icon={ListTodo} accent="sky" loading={queueStatsQuery.isLoading} />
        <StatCard label="Failed Tasks" value={failedTasks} icon={ListTodo} accent="rose" loading={queueStatsQuery.isLoading} />
      </section>

      {/* Activity chart + Response rates */}
      <section className="grid gap-6 xl:grid-cols-2">
        {/* Daily Activity Chart */}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Daily Activity</h2>
          <p className="text-sm text-slate-500">Queue executions over the last 14 days</p>
          <div className="mt-5">
            {dailyQuery.isLoading ? (
              <div className="h-40 animate-pulse rounded-xl bg-slate-100" />
            ) : (() => {
              const rows = dailyQuery.data || []
              // aggregate by day
              const byDay: Record<string, { sent: number; failed: number; queued: number }> = {}
              rows.forEach((r) => {
                const d = r.day?.slice(0, 10) || ''
                if (!byDay[d]) byDay[d] = { sent: 0, failed: 0, queued: 0 }
                if (r.status === 'sent') byDay[d].sent += r.cnt
                else if (r.status === 'failed') byDay[d].failed += r.cnt
                else byDay[d].queued += r.cnt
              })
              const days = Object.keys(byDay).sort()
              if (days.length === 0) return <p className="py-8 text-center text-sm text-slate-400">No activity data</p>
              const maxVal = Math.max(1, ...days.map((d) => byDay[d].sent + byDay[d].failed + byDay[d].queued))
              return (
                <div className="flex items-end gap-1" style={{ height: 140 }}>
                  {days.map((d) => {
                    const { sent, failed, queued } = byDay[d]
                    const total = sent + failed + queued
                    const pct = (total / maxVal) * 100
                    return (
                      <div key={d} className="group relative flex flex-1 flex-col items-center">
                        <div className="absolute -top-8 hidden rounded-lg bg-slate-800 px-2 py-1 text-[10px] text-white group-hover:block">
                          {d.slice(5)}: {sent}s / {failed}f
                        </div>
                        <div className="flex w-full flex-col" style={{ height: `${pct}%`, minHeight: 4 }}>
                          {sent > 0 && <div className="w-full rounded-t bg-emerald-400" style={{ flex: sent }} />}
                          {failed > 0 && <div className="w-full bg-rose-400" style={{ flex: failed }} />}
                          {queued > 0 && <div className="w-full rounded-b bg-sky-300" style={{ flex: queued }} />}
                        </div>
                        <span className="mt-1 text-[9px] text-slate-400">{d.slice(8)}</span>
                      </div>
                    )
                  })}
                </div>
              )
            })()}
            <div className="mt-3 flex gap-4 text-[10px] text-slate-400">
              <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />Sent</span>
              <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-rose-400" />Failed</span>
              <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-sky-300" />Queued</span>
            </div>
          </div>
        </div>

        {/* Response Rates */}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Response Rates</h2>
          <p className="text-sm text-slate-500">Invite → Accept → Reply funnel per campaign</p>
          <div className="mt-5 space-y-4">
            {ratesQuery.isLoading ? (
              <div className="space-y-3">
                {[1, 2, 3].map((i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-slate-100" />)}
              </div>
            ) : (ratesQuery.data || []).length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-400">No campaign data</p>
            ) : (
              (ratesQuery.data || []).map((c) => {
                const acceptRate = c.invited > 0 ? Math.round((c.accepted / c.invited) * 100) : 0
                const replyRate = c.accepted > 0 ? Math.round((c.replied / c.accepted) * 100) : 0
                return (
                  <div key={c.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="flex items-center justify-between">
                      <span className="truncate text-sm font-medium text-slate-900">{c.name}</span>
                      <span className="text-xs text-slate-400">{c.total} leads</span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-3">
                      <div>
                        <div className="flex items-center justify-between text-[10px] text-slate-400">
                          <span>Accept rate</span>
                          <span className="font-semibold text-emerald-600">{acceptRate}%</span>
                        </div>
                        <div className="mt-1 h-1.5 rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-emerald-400 transition-all" style={{ width: `${acceptRate}%` }} />
                        </div>
                      </div>
                      <div>
                        <div className="flex items-center justify-between text-[10px] text-slate-400">
                          <span>Reply rate</span>
                          <span className="font-semibold text-sky-600">{replyRate}%</span>
                        </div>
                        <div className="mt-1 h-1.5 rounded-full bg-slate-200">
                          <div className="h-full rounded-full bg-sky-400 transition-all" style={{ width: `${replyRate}%` }} />
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </section>

      {/* Bottom panels */}
      <section className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
        {/* Channel breakdown */}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4">
            <h2 className="text-lg font-semibold text-slate-900">Channel breakdown</h2>
            <p className="text-sm text-slate-500">Queue performance grouped by channel and state.</p>
          </div>
          <DataTable
            columns={[
              { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
              { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
              { key: 'count', header: 'Count', className: 'text-right tabular-nums' },
            ]}
            rows={breakdownRows}
            loading={queueStatsQuery.isLoading}
            emptyMessage="No queue activity yet."
          />
        </div>

        {/* Campaign footprint */}
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Campaigns</h2>
          <p className="mt-1 text-sm text-slate-500">Current state at a glance.</p>
          <div className="mt-5 space-y-3">
            {campaignsQuery.isLoading ? (
              <>
                <div className="skeleton h-20 w-full rounded-2xl" />
                <div className="skeleton h-20 w-full rounded-2xl" />
                <div className="skeleton h-20 w-full rounded-2xl" />
              </>
            ) : campaigns.length === 0 ? (
              <EmptyState
                icon={Megaphone}
                title="No campaigns"
                description="Create a campaign to start the pipeline."
                action={<Link to="/campaigns" className="text-sm font-medium text-sky-500 hover:text-sky-600">Create one</Link>}
              />
            ) : (
              campaigns.slice(0, 6).map((campaign) => (
                <Link
                  key={campaign.id}
                  to={`/campaigns/${campaign.id}?tab=leads`}
                  className="block rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 hover:bg-slate-100 transition-colors"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-900">{campaign.name}</p>
                      <p className="mt-0.5 text-xs uppercase tracking-[0.14em] text-slate-400">{campaign.timezone}</p>
                    </div>
                    <Badge
                      label={campaign.simulation_mode ? 'simulation' : 'live'}
                      variant={campaign.simulation_mode ? 'warning' : 'success'}
                    />
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
                    <span>Daily cap: <span className="font-semibold text-slate-800">{campaign.daily_lead_cap}</span></span>
                    <span>Invite cap: <span className="font-semibold text-slate-800">{campaign.invite_daily_cap}</span></span>
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
