import { useMemo, useState } from 'react'
import { Inbox, RefreshCw, RotateCcw, AlertCircle } from 'lucide-react'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import StatCard from '../components/StatCard'
import { useToast } from '../components/Toast'
import { useListCampaigns } from '../hooks/useCampaigns'
import { useQueueList, useQueueStats, useRetryTask, useBulkRetryTasks } from '../hooks/useQueue'
import { formatRelative, formatScheduled } from '../lib/time'

export default function Queue() {
  const toast = useToast()
  const campaignsQuery = useListCampaigns()
  const [campaignId, setCampaignId] = useState('')
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')

  const queueStatsQuery = useQueueStats()
  const queueQuery = useQueueList({ campaignId: campaignId || undefined, status: status || undefined, limit: 200 })
  const retryTask = useRetryTask()
  const bulkRetry = useBulkRetryTasks()

  const campaignMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const c of campaignsQuery.data || []) map[c.id] = c.name
    return map
  }, [campaignsQuery.data])

  const tasks = useMemo(
    () => (queueQuery.data || []).filter((t) => !channel || t.channel === channel),
    [queueQuery.data, channel],
  )

  const stats = queueStatsQuery.data || []
  const queued  = stats.filter((r) => r.status === 'queued').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const locked  = stats.filter((r) => r.status === 'locked').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const sent    = stats.filter((r) => r.status === 'sent').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const failed  = stats.filter((r) => r.status === 'failed').reduce((s, r) => s + Number(r.cnt || 0), 0)

  const channels = useMemo(
    () => [...new Set((queueQuery.data || []).map((t) => t.channel))],
    [queueQuery.data],
  )

  const handleRetry = async (id: string) => {
    try {
      await retryTask.mutateAsync(id)
      toast.success('Task reset to queued')
    } catch {
      toast.error('Failed to retry task')
    }
  }

  const handleBulkRetry = async () => {
    if (!window.confirm('Retry all failed tasks matching current filters?')) return
    try {
      await bulkRetry.mutateAsync({ campaignId: campaignId || undefined, channel: channel || undefined })
      toast.success('Failed tasks reset to queued')
    } catch {
      toast.error('Bulk retry failed')
    }
  }

  const lastRefreshed = queueQuery.dataUpdatedAt

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Queue</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              Watch scheduled outreach before it becomes customer-visible
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Filter by campaign, channel, and status to spot backlog pressure or failed tasks quickly.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            {lastRefreshed > 0 && (
              <div className="shrink-0 flex items-center gap-1.5 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-400">
                <RefreshCw size={12} />
                Updated {formatRelative(new Date(lastRefreshed).toISOString())}
              </div>
            )}
            {failed > 0 && (
              <button
                onClick={handleBulkRetry}
                disabled={bulkRetry.isPending}
                className="btn-tactile flex items-center gap-2 rounded-xl bg-rose-50 px-4 py-2 text-xs font-bold text-rose-600 border border-rose-100 hover:bg-rose-100 transition-all shadow-sm shadow-rose-100/50"
              >
                <RotateCcw size={13} className={bulkRetry.isPending ? 'animate-spin' : ''} />
                Retry {failed} Failures
              </button>
            )}
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Queued"  value={queued}  loading={queueStatsQuery.isLoading} />
        <StatCard label="Locked"  value={locked}  accent="amber"   loading={queueStatsQuery.isLoading} />
        <StatCard label="Sent"    value={sent}    accent="emerald" loading={queueStatsQuery.isLoading} />
        <StatCard label="Failed"  value={failed}  accent="rose"    loading={queueStatsQuery.isLoading} />
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="grid gap-3 md:grid-cols-3 mb-6">
          <select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} className={inputCls}>
            <option value="">All campaigns</option>
            {(campaignsQuery.data || []).map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
          <select value={channel} onChange={(e) => setChannel(e.target.value)} className={inputCls}>
            <option value="">All channels</option>
            {channels.map((ch) => (
              <option key={ch} value={ch}>{ch.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)} className={inputCls}>
            <option value="">All statuses</option>
            <option value="queued">queued</option>
            <option value="locked">locked</option>
            <option value="sent">sent</option>
            <option value="failed">failed</option>
            <option value="skipped">skipped</option>
          </select>
        </div>

        {tasks.length === 0 && !queueQuery.isLoading ? (
          <EmptyState
            icon={Inbox}
            title="No tasks match this filter"
            description="Try widening the campaign or status scope."
          />
        ) : (
          <DataTable
            columns={[
              {
                key: 'lead',
                header: 'Lead',
                render: (row) => (
                  <div className="flex flex-col">
                    <span className="font-medium text-slate-900">
                      {`${row.first_name || ''} ${row.last_name || ''}`.trim() || row.linkedin_url || 'Unknown'}
                    </span>
                    {row.failure_reason && (
                      <div className="flex items-center gap-1 mt-1 text-[10px] text-rose-500 font-medium">
                        <AlertCircle size={10} />
                        <span className="truncate max-w-[180px]" title={row.failure_reason}>{row.failure_reason}</span>
                      </div>
                    )}
                  </div>
                ),
              },
              {
                key: 'campaign_id',
                header: 'Campaign',
                render: (row) => (
                  <span className="text-slate-600">
                    {campaignMap[row.campaign_id] ?? <span className="font-mono text-xs text-slate-400">{row.campaign_id.slice(0, 8)}</span>}
                  </span>
                ),
              },
              { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
              { key: 'status',  header: 'Status',  render: (row) => <Badge label={row.status}  asStatus  /> },
              {
                key: 'scheduled_at',
                header: 'Scheduled',
                render: (row) => (
                  <span className="tabular-nums text-slate-500 text-xs">
                    {formatScheduled(row.scheduled_at)}
                  </span>
                ),
              },
              {
                key: 'retry_count',
                header: 'Retries',
                render: (row) => (
                  <span className={row.retry_count ? 'text-amber-600 font-medium' : 'text-slate-400'}>
                    {row.retry_count || 0}
                  </span>
                ),
              },
              {
                key: 'actions',
                header: '',
                className: 'text-right',
                render: (row) => (row.status === 'failed' || row.status === 'skipped') && (
                  <button
                    onClick={() => handleRetry(row.id)}
                    disabled={retryTask.isPending}
                    className="p-2 rounded-lg text-slate-400 hover:text-sky-600 hover:bg-sky-50 transition-all"
                    title="Retry task"
                  >
                    <RotateCcw size={14} className={retryTask.isPending ? 'animate-spin' : ''} />
                  </button>
                ),
              },
            ]}
            rows={tasks}
            loading={queueQuery.isLoading}
            emptyMessage="No queue tasks yet."
          />
        )}
      </section>
    </div>
  )
}

const inputCls =
  'w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100'
