import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity as ActivityIcon, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import Badge from '../components/Badge'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'
import { timeAgo, buildQuery } from '../lib/format'

interface ActivityRow { id: string; action: string; detail?: string; created_at: string }
interface Campaign { id: string; name: string }

export default function Activity() {
  const [campaignId, setCampaignId] = useState('')
  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const activityQ = useQuery<{ activity: ActivityRow[] }>({
    queryKey: ['activity', campaignId],
    queryFn: () => api.get(`/activity${buildQuery({ campaign_id: campaignId, limit: 200 })}`).then(r => r.data),
  })

  const items = activityQ.data?.activity || []

  const verbColor: Record<string, string> = {
    create: 'bg-emerald-50 text-emerald-600',
    update: 'bg-amber-50 text-amber-600',
    delete: 'bg-rose-50 text-rose-600',
    error: 'bg-rose-50 text-rose-600',
  }

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Activity"
        eyebrow="Audit"
        title="Activity log"
        description="Every action the system or operators took — campaigns paused, leads imported, approvals resolved."
        actions={<Button variant="secondary" size="md" icon={RefreshCw} onClick={() => activityQ.refetch()}>Refresh</Button>}
      />

      <FilterBar>
        <SearchInput placeholder="Search actions, details…" value="" onChange={() => {}} />
        <Select value={campaignId} onChange={setCampaignId}>
          <option value="">All campaigns</option>
          {(campaignsQ.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </FilterBar>

      {activityQ.isLoading ? (
        <div className="space-y-2">{[0,1,2,3,4].map(i => <div key={i} className="h-14 skeleton rounded-2xl" />)}</div>
      ) : items.length === 0 ? (
        <Card padding="lg">
          <EmptyState icon={ActivityIcon} title="No activity yet" description="System and operator actions will stream in here." />
        </Card>
      ) : (
        <Card padding="none">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {items.map(row => {
              const [category, action] = (row.action || '').split('.')
              const verb = category.toLowerCase()
              const color = verbColor[verb] || 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
              return (
                <li key={row.id} className="flex items-start gap-4 px-6 py-4 transition-colors hover:bg-slate-50/50 dark:hover:bg-slate-900/50">
                  <div className={clsx('mt-0.5 flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-xl', color)}>
                    <ActivityIcon size={14} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="truncate text-sm font-bold text-slate-900 dark:text-white">
                          {action || category || 'System Event'}
                        </span>
                        <Badge label={category} variant="neutral" size="xs" />
                      </div>
                      <span className="flex-shrink-0 text-[11px] font-bold tabular-nums text-slate-400 uppercase tracking-wider">
                        {timeAgo(row.created_at)}
                      </span>
                    </div>
                    {row.detail && (
                      <p className="mt-1 line-clamp-2 text-[13px] font-medium text-slate-500 dark:text-slate-400">
                        {row.detail}
                      </p>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        </Card>
      )}
    </div>
  )
}
