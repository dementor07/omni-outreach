import { Activity, CheckCircle2, ListTodo, Megaphone, Send, Users } from 'lucide-react'
import { Link } from 'react-router-dom'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import StatCard from '../components/StatCard'
import { useListCampaigns } from '../hooks/useCampaigns'
import { useQueueStats } from '../hooks/useQueue'
import { useOverviewStats } from '../hooks/useOverview'
import { formatRelative, formatScheduled } from '../lib/time'

export default function Dashboard() {
  const campaignsQuery = useListCampaigns()
  const queueStatsQuery = useQueueStats()
  const overviewQuery = useOverviewStats()

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
