import { useQuery } from '@tanstack/react-query'
import { Activity, Filter } from 'lucide-react'
import { useState } from 'react'

import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useListCampaigns } from '../hooks/useCampaigns'
import { api } from '../api/client'
import { timeAgo } from '../lib/time'

interface ActivityEntry {
  id: string
  action: string
  detail?: string
  campaign_id?: string
  lead_id?: string
  created_at: string
}

const ACTION_COLORS: Record<string, string> = {
  lead_imported: 'emerald',
  invite_sent: 'sky',
  dm_sent: 'sky',
  email_sent: 'sky',
  reply_received: 'amber',
  lead_stopped: 'rose',
  task_failed: 'rose',
  campaign_activated: 'emerald',
  campaign_paused: 'amber',
  graph_saved: 'sky',
}

export default function ActivityPage() {
  const [campaignId, setCampaignId] = useState('')
  const campaignsQuery = useListCampaigns()

  const activityQuery = useQuery({
    queryKey: ['activity', campaignId],
    queryFn: async () => {
      const params = campaignId ? `?campaign_id=${campaignId}&limit=100` : '?limit=100'
      const { data } = await api.get<{ activity: ActivityEntry[] }>(`/activity${params}`)
      return data.activity
    },
    refetchInterval: 15_000,
  })

  const entries = activityQuery.data ?? []

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Activity</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
              System-wide activity feed
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Every action across all campaigns in one timeline. Filter by campaign to focus.
            </p>
          </div>
          <div className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <Filter size={14} className="text-slate-400" />
            <select
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
              className="bg-transparent text-sm text-slate-700 outline-none"
            >
              <option value="">All campaigns</option>
              {(campaignsQuery.data ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        {activityQuery.isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <div key={i} className="skeleton h-12 w-full rounded-xl" />
            ))}
          </div>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No activity yet"
            description="Actions will appear here as campaigns run."
          />
        ) : (
          <div className="space-y-1">
            {entries.map((entry) => (
              <div
                key={entry.id}
                className="flex items-center gap-4 rounded-xl px-4 py-3 hover:bg-slate-50 transition-colors"
              >
                <div className="shrink-0">
                  <Badge label={entry.action.replace(/_/g, ' ')} variant={ACTION_COLORS[entry.action] as any || 'default'} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-slate-700 truncate">{entry.detail || entry.action}</p>
                </div>
                <span className="shrink-0 text-xs text-slate-400 tabular-nums">{timeAgo(entry.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
