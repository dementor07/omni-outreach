import { useMemo, useState } from 'react'
import { Inbox } from 'lucide-react'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import StatCard from '../components/StatCard'
import { useListCampaigns } from '../hooks/useCampaigns'
import { useQueueList, useQueueStats } from '../hooks/useQueue'

function formatDate(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

export default function Queue() {
  const campaignsQuery = useListCampaigns()
  const [campaignId, setCampaignId] = useState('')
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')

  const queueStatsQuery = useQueueStats()
  const queueQuery = useQueueList({ campaignId: campaignId || undefined, status: status || undefined, limit: 150 })

  const tasks = (queueQuery.data || []).filter((task) => !channel || task.channel === channel)
  const stats = queueStatsQuery.data || []

  const queued = stats.filter((row) => row.status === 'queued').reduce((sum, row) => sum + Number(row.cnt || 0), 0)
  const locked = stats.filter((row) => row.status === 'locked').reduce((sum, row) => sum + Number(row.cnt || 0), 0)
  const sent = stats.filter((row) => row.status === 'sent').reduce((sum, row) => sum + Number(row.cnt || 0), 0)
  const failed = stats.filter((row) => row.status === 'failed').reduce((sum, row) => sum + Number(row.cnt || 0), 0)

  const channels = useMemo(() => [...new Set((queueQuery.data || []).map((task) => task.channel))], [queueQuery.data])

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Queue</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Watch scheduled outreach before it becomes customer-visible</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
          Filter by campaign, channel, and status to spot backlog pressure or failed work quickly.
        </p>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Queued" value={queued} loading={queueStatsQuery.isLoading} />
        <StatCard label="Locked" value={locked} accent="amber" loading={queueStatsQuery.isLoading} />
        <StatCard label="Sent" value={sent} accent="emerald" loading={queueStatsQuery.isLoading} />
        <StatCard label="Failed" value={failed} accent="rose" loading={queueStatsQuery.isLoading} />
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="grid gap-4 md:grid-cols-3">
          <select value={campaignId} onChange={(event) => setCampaignId(event.target.value)} className={inputClassName}>
            <option value="">All campaigns</option>
            {(campaignsQuery.data || []).map((campaign) => (
              <option key={campaign.id} value={campaign.id}>
                {campaign.name}
              </option>
            ))}
          </select>
          <select value={channel} onChange={(event) => setChannel(event.target.value)} className={inputClassName}>
            <option value="">All channels</option>
            {channels.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <select value={status} onChange={(event) => setStatus(event.target.value)} className={inputClassName}>
            <option value="">All statuses</option>
            <option value="queued">queued</option>
            <option value="locked">locked</option>
            <option value="sent">sent</option>
            <option value="failed">failed</option>
            <option value="skipped">skipped</option>
          </select>
        </div>

        <div className="mt-6">
          {tasks.length === 0 && !queueQuery.isLoading ? (
            <EmptyState icon={Inbox} title="No queue tasks match this filter" description="Try widening the campaign or status scope." />
          ) : (
            <DataTable
              columns={[
                {
                  key: 'lead',
                  header: 'Lead',
                  render: (row) => `${row.first_name || ''} ${row.last_name || ''}`.trim() || row.linkedin_url || 'Unknown',
                },
                { key: 'campaign_id', header: 'Campaign' },
                { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
                { key: 'scheduled_at', header: 'Scheduled at', render: (row) => formatDate(row.scheduled_at) },
                { key: 'retry_count', header: 'Retries', className: 'text-right', render: (row) => row.retry_count || 0 },
              ]}
              rows={tasks}
              loading={queueQuery.isLoading}
              emptyMessage="No queue tasks yet."
            />
          )}
        </div>
      </section>
    </div>
  )
}

const inputClassName =
  'w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100'
