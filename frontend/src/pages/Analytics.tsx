import { useState } from 'react'
import { BarChart3, TrendingUp, Users, Mail, ArrowDown, ChevronDown } from 'lucide-react'
import { useListCampaigns } from '../hooks/useCampaigns'
import { useCampaignAnalytics } from '../hooks/useAnalytics'

function FunnelBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? (value / total) * 100 : 0
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-slate-600">{label}</span>
        <span className="font-semibold text-slate-900">{value}</span>
      </div>
      <div className="h-3 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${Math.max(pct, 2)}%` }}
        />
      </div>
    </div>
  )
}

function StatBox({ label, value, suffix }: { label: string; value: string | number; suffix?: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-5 py-4">
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-bold text-slate-900">
        {value}{suffix && <span className="ml-0.5 text-sm font-medium text-slate-400">{suffix}</span>}
      </div>
    </div>
  )
}

export default function Analytics() {
  const [campaignId, setCampaignId] = useState('')
  const campaigns = useListCampaigns()
  const { data, isLoading } = useCampaignAnalytics(campaignId || undefined)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Campaign Analytics</h1>
          <p className="mt-1 text-sm text-slate-500">Funnel metrics, conversion rates, and activity trends</p>
        </div>
        <select
          value={campaignId}
          onChange={(e) => setCampaignId(e.target.value)}
          className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm outline-none"
        >
          <option value="">Select campaign</option>
          {(campaigns.data || []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {!campaignId ? (
        <div className="flex flex-col items-center gap-3 py-20 text-slate-400">
          <BarChart3 size={40} />
          <p className="text-sm">Select a campaign to view analytics</p>
        </div>
      ) : isLoading ? (
        <div className="grid gap-4 md:grid-cols-3">
          {[1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-2xl bg-slate-100" />)}
        </div>
      ) : data ? (
        <>
          {/* Key metrics */}
          <div className="grid gap-4 md:grid-cols-4">
            <StatBox label="Total Leads" value={data.funnel.total_leads} />
            <StatBox label="Invite Rate" value={data.rates.invite_rate} suffix="%" />
            <StatBox label="Accept Rate" value={data.rates.accept_rate} suffix="%" />
            <StatBox label="Reply Rate" value={data.rates.reply_rate} suffix="%" />
          </div>

          {/* Funnel */}
          <div className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">Conversion Funnel</h2>
            <div className="space-y-4">
              <FunnelBar label="Total Leads" value={data.funnel.total_leads} total={data.funnel.total_leads} color="bg-slate-400" />
              <FunnelBar label="Invited" value={data.funnel.invited} total={data.funnel.total_leads} color="bg-sky-500" />
              <FunnelBar label="Accepted" value={data.funnel.accepted} total={data.funnel.total_leads} color="bg-emerald-500" />
              <FunnelBar label="Replied" value={data.funnel.replied} total={data.funnel.total_leads} color="bg-violet-500" />
              <FunnelBar label="Stopped" value={data.funnel.stopped} total={data.funnel.total_leads} color="bg-rose-400" />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            {/* Event type breakdown */}
            <div className="rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">Event Types</h2>
              {data.event_counts.length === 0 ? (
                <p className="text-sm text-slate-400">No events recorded yet.</p>
              ) : (
                <div className="space-y-2">
                  {data.event_counts.map((ec) => (
                    <div key={ec.event_type} className="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2">
                      <span className="text-sm text-slate-700">{ec.event_type.replace(/_/g, ' ')}</span>
                      <span className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-semibold text-sky-700">{ec.cnt}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Channel breakdown */}
            <div className="rounded-2xl border border-slate-200 bg-white p-6">
              <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">Channels</h2>
              {data.channel_breakdown.length === 0 ? (
                <p className="text-sm text-slate-400">No channel data yet.</p>
              ) : (
                <div className="space-y-2">
                  {data.channel_breakdown.map((ch) => (
                    <div key={ch.channel} className="flex items-center justify-between rounded-xl bg-slate-50 px-3 py-2">
                      <span className="text-sm capitalize text-slate-700">{ch.channel}</span>
                      <span className="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold text-violet-700">{ch.cnt}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Daily activity */}
          <div className="rounded-2xl border border-slate-200 bg-white p-6">
            <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-400">Daily Activity (Last 30 Days)</h2>
            {data.daily_activity.length === 0 ? (
              <p className="text-sm text-slate-400">No activity in the last 30 days.</p>
            ) : (
              <div className="flex items-end gap-1" style={{ height: 120 }}>
                {data.daily_activity.map((d) => {
                  const maxEvents = Math.max(...data.daily_activity.map((x) => x.events), 1)
                  const h = (d.events / maxEvents) * 100
                  return (
                    <div key={d.day} className="group relative flex-1" title={`${d.day}: ${d.events} events`}>
                      <div
                        className="w-full rounded-t bg-sky-400 transition-colors group-hover:bg-sky-600"
                        style={{ height: `${Math.max(h, 4)}%` }}
                      />
                      <div className="pointer-events-none absolute bottom-full left-1/2 mb-1 hidden -translate-x-1/2 rounded bg-slate-800 px-2 py-1 text-[10px] text-white group-hover:block">
                        {d.day}: {d.events}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}
