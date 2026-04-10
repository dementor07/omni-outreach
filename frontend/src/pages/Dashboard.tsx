import { Activity, CheckCircle2, ListTodo, MessageSquare, Send, Users } from 'lucide-react'

import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import StatCard from '../components/StatCard'
import { useListCampaigns } from '../hooks/useCampaigns'
import { useQueueStats } from '../hooks/useQueue'

function formatNumber(value: number | undefined) {
  return (value || 0).toLocaleString()
}

export default function Dashboard() {
  const campaignsQuery = useListCampaigns()
  const queueStatsQuery = useQueueStats()

  const campaigns = campaignsQuery.data || []
  const stats = queueStatsQuery.data || []

  const totalLeads = campaigns.reduce((sum, campaign) => sum + (campaign.daily_lead_cap || 0), 0)
  const activeCampaigns = campaigns.filter((campaign) => campaign.status !== 'archived').length
  const invited = stats
    .filter((row) => row.channel === 'linkedin_invite' && row.status === 'sent')
    .reduce((sum, row) => sum + Number(row.cnt || 0), 0)
  const accepted = stats
    .filter((row) => row.channel === 'linkedin_dm' && row.status === 'sent')
    .reduce((sum, row) => sum + Number(row.cnt || 0), 0)
  const queuedTasks = stats
    .filter((row) => row.status === 'queued')
    .reduce((sum, row) => sum + Number(row.cnt || 0), 0)
  const failedTasks = stats
    .filter((row) => row.status === 'failed')
    .reduce((sum, row) => sum + Number(row.cnt || 0), 0)

  const breakdownRows = stats.map((row, index) => ({
    id: `${row.channel}-${row.status}-${index}`,
    channel: row.channel,
    status: row.status,
    count: Number(row.cnt || 0),
  }))

  return (
    <div className="space-y-8">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Overview</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Mission control for outreach operations</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Monitor queue pressure, campaign load, and channel delivery from one place.
            </p>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-sm text-slate-600">
            <div className="font-medium text-slate-900">Live data</div>
            <div className="mt-1">Queue stats auto-refresh every 30 seconds.</div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Total Lead Capacity" value={formatNumber(totalLeads)} icon={Users} accent="sky" loading={campaignsQuery.isLoading} />
        <StatCard label="Invited" value={formatNumber(invited)} icon={Send} accent="emerald" loading={queueStatsQuery.isLoading} />
        <StatCard label="Accepted / DM Sent" value={formatNumber(accepted)} icon={CheckCircle2} accent="amber" loading={queueStatsQuery.isLoading} />
        <StatCard label="Queued Tasks" value={formatNumber(queuedTasks)} icon={ListTodo} accent="sky" loading={queueStatsQuery.isLoading} />
        <StatCard label="Active Campaigns" value={formatNumber(activeCampaigns)} icon={Activity} accent="emerald" loading={campaignsQuery.isLoading} />
        <StatCard label="Failed Tasks" value={formatNumber(failedTasks)} icon={MessageSquare} accent="rose" loading={queueStatsQuery.isLoading} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.25fr_0.75fr]">
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-slate-900">Channel breakdown</h2>
              <p className="text-sm text-slate-500">Queue performance grouped by channel and state.</p>
            </div>
          </div>
          <DataTable
            columns={[
              { key: 'channel', header: 'Channel' },
              { key: 'status', header: 'Status' },
              { key: 'count', header: 'Count', className: 'text-right' },
            ]}
            rows={breakdownRows}
            loading={queueStatsQuery.isLoading}
            emptyMessage="No queue activity yet."
          />
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Campaign footprint</h2>
          <p className="mt-1 text-sm text-slate-500">Recently created campaigns and their current simulation state.</p>
          <div className="mt-5 space-y-3">
            {campaignsQuery.isLoading ? (
              <div className="space-y-3">
                <div className="skeleton h-20 w-full" />
                <div className="skeleton h-20 w-full" />
                <div className="skeleton h-20 w-full" />
              </div>
            ) : campaigns.length === 0 ? (
              <EmptyState icon={Users} title="No campaigns yet" description="Create a campaign to start feeding the pipeline." />
            ) : (
              campaigns.slice(0, 5).map((campaign) => (
                <div key={campaign.id} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="font-semibold text-slate-900">{campaign.name}</p>
                      <p className="mt-1 text-xs uppercase tracking-[0.16em] text-slate-400">{campaign.timezone}</p>
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${campaign.simulation_mode ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>
                      {campaign.simulation_mode ? 'Simulation' : 'Live'}
                    </span>
                  </div>
                  <div className="mt-4 grid grid-cols-2 gap-3 text-sm text-slate-500">
                    <div>
                      <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Daily leads</div>
                      <div className="mt-1 font-semibold text-slate-900">{campaign.daily_lead_cap}</div>
                    </div>
                    <div>
                      <div className="text-xs uppercase tracking-[0.14em] text-slate-400">Invite cap</div>
                      <div className="mt-1 font-semibold text-slate-900">{campaign.invite_daily_cap}</div>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
