import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Clock, Lock, Send, AlertCircle, RefreshCw, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import DataTable from '../components/DataTable'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'
import Avatar from '../components/Avatar'
import ChannelIcon from '../components/ChannelIcon'
import { fullName, formatScheduled } from '../lib/format'
import { Inbox } from 'lucide-react'
import { clsx } from 'clsx'

interface QueueTask { id: string; first_name?: string; last_name?: string; linkedin_url?: string; email?: string; campaign_id?: string; channel: string; status: string; scheduled_at?: string; retry_count?: number; failure_reason?: string }
interface Campaign { id: string; name: string }

export default function Queue() {
  const [campaignId, setCampaignId] = useState('')
  const [status, setStatus] = useState('')
  const [channel, setChannel] = useState('')

  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const statsQ = useQuery<{ stats: { channel: string; status: string; cnt: number }[] }>({ queryKey: ['queue-stats'], queryFn: () => api.get('/queue/stats').then(r => r.data) })

  const params = new URLSearchParams()
  if (campaignId) params.set('campaign_id', campaignId)
  if (status) params.set('status', status)
  params.set('limit', '200')
  const queueQ = useQuery<{ tasks: QueueTask[] }>({ queryKey: ['queue', campaignId, status], queryFn: () => api.get(`/queue?${params.toString()}`).then(r => r.data) })

  const tasks = (queueQ.data?.tasks || []).filter(t => !channel || t.channel === channel)
  const qStats = statsQ.data?.stats || []
  const queued = qStats.filter(r => r.status === 'queued').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const locked = qStats.filter(r => r.status === 'locked').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const sent = qStats.filter(r => r.status === 'sent').reduce((s, r) => s + Number(r.cnt || 0), 0)
  const failed = qStats.filter(r => r.status === 'failed').reduce((s, r) => s + Number(r.cnt || 0), 0)

  const channels = [...new Set((queueQ.data?.tasks || []).map(t => t.channel))]
  const campaignMap = useMemo(() => {
    const m: Record<string, string> = {};
    (campaignsQ.data || []).forEach(c => { m[c.id] = c.name })
    return m
  }, [campaignsQ.data])

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Queue"
        eyebrow="Pipeline"
        title="Queue"
        description="Scheduled outreach before it becomes customer-visible. Filter by campaign, channel, and state to spot backlog pressure or failed tasks."
        actions={
          <>
            <Button variant="secondary" size="md" icon={RefreshCw} onClick={() => { queueQ.refetch(); statsQ.refetch() }}>Refresh</Button>
            {failed > 0 && <Button variant="danger" size="md" icon={RotateCcw}>Retry {failed.toLocaleString()} failures</Button>}
          </>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Queued" value={statsQ.isLoading ? '—' : queued} accent="brand" icon={Clock} />
        <StatCard label="Locked" value={statsQ.isLoading ? '—' : locked} accent="amber" icon={Lock} />
        <StatCard label="Sent" value={statsQ.isLoading ? '—' : sent} accent="emerald" icon={Send} />
        <StatCard label="Failed" value={statsQ.isLoading ? '—' : failed} accent="rose" icon={AlertCircle} />
      </section>

      <FilterBar>
        <SearchInput placeholder="Search by lead, company, or campaign…" value="" onChange={() => {}} />
        <Select value={campaignId} onChange={setCampaignId}>
          <option value="">All campaigns</option>
          {(campaignsQ.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <Select value={channel} onChange={setChannel}>
          <option value="">All channels</option>
          {channels.map(ch => <option key={ch} value={ch}>{(ch || '').replace(/_/g, ' ')}</option>)}
        </Select>
        <Select value={status} onChange={setStatus}>
          <option value="">All statuses</option>
          {['queued', 'locked', 'sent', 'failed', 'skipped'].map(s => <option key={s} value={s}>{s}</option>)}
        </Select>
      </FilterBar>

      <Card padding="none">
        {queueQ.isLoading ? (
          <div className="space-y-1 p-4">{[0,1,2,3,4].map(i => <div key={i} className="h-12 skeleton" />)}</div>
        ) : tasks.length === 0 ? (
          <EmptyState icon={Inbox} title="No queued tasks" description="Tasks appear here as soon as the sequencer schedules them." />
        ) : (
          <DataTable
            columns={[
              { key: 'lead', header: 'Lead', render: (row: QueueTask) => (
                <div className="flex items-center gap-2.5">
                  <Avatar name={fullName(row)} size={28} />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900 dark:text-white">{fullName(row)}</div>
                    {row.failure_reason && (
                      <div className="mt-0.5 flex items-center gap-1 truncate text-[11px] text-rose-500">
                        <AlertCircle size={11} /><span className="truncate">{row.failure_reason}</span>
                      </div>
                    )}
                  </div>
                </div>
              )},
              { key: 'campaign', header: 'Campaign', render: (row: QueueTask) => row.campaign_id
                ? <span className="text-slate-600 dark:text-slate-300">{campaignMap[row.campaign_id] ?? <span className="font-mono text-xs text-slate-400">{String(row.campaign_id).slice(0,8)}</span>}</span>
                : <span className="text-slate-300">—</span>
              },
              { key: 'channel', header: 'Channel', render: (row: QueueTask) => (
                <div className="flex items-center gap-2">
                  <ChannelIcon channel={row.channel} size="sm" />
                  <span className="capitalize text-slate-700 dark:text-slate-300">{(row.channel || '').replace(/_/g, ' ')}</span>
                </div>
              )},
              { key: 'status', header: 'Status', render: (row: QueueTask) => <Badge label={row.status} asStatus dot /> },
              { key: 'scheduled_at', header: 'Scheduled', render: (row: QueueTask) => <span className="text-xs tabular-nums text-slate-500">{formatScheduled(row.scheduled_at)}</span> },
              { key: 'retry_count', header: 'Retries', align: 'right' as const, render: (row: QueueTask) => (
                <span className={clsx('text-xs tabular-nums', row.retry_count ? 'font-semibold text-amber-600' : 'text-slate-400')}>
                  {row.retry_count || 0}
                </span>
              )},
              { key: 'actions', header: '', align: 'right' as const, render: (row: QueueTask) =>
                (row.status === 'failed' || row.status === 'skipped') ? <Button variant="ghost" size="sm" icon={RotateCcw}>Retry</Button> : null
              },
            ]}
            rows={tasks}
          />
        )}
      </Card>
    </div>
  )
}
