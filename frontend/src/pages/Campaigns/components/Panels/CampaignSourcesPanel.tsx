import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Database, ChevronRight, Clock } from 'lucide-react'
import { api } from '../../../../api/client'
import { useToast } from '../../../../components/Toast'
import { CampaignConfig, CampaignRun } from '../../types'

export function CampaignSourcesPanel({ campaignId }: { campaignId: string }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [runningId, setRunningId] = useState<string | null>(null)

  const configsQuery = useQuery<CampaignConfig[]>({
    queryKey: ['lead-gen-configs', campaignId],
    queryFn: () => api.get(`/lead-gen/configs/${campaignId}`).then(r => r.data),
  })
  const runsQuery = useQuery<CampaignRun[]>({
    queryKey: ['lead-gen-runs', 'campaign', campaignId],
    queryFn: () => api.get(`/lead-gen/runs?campaign_id=${campaignId}&limit=10`).then(r => r.data),
    refetchInterval: 15_000,
  })

  const runMutation = useMutation({
    mutationFn: (configId: string) =>
      api.post('/lead-gen/trigger', { campaign_id: campaignId, config_id: configId }).then(r => r.data),
    onSuccess: () => {
      setRunningId(null)
      toast.success('Run started')
      void queryClient.invalidateQueries({ queryKey: ['lead-gen-runs', 'campaign', campaignId] })
    },
    onError: (err: unknown) => {
      setRunningId(null)
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Failed to start run')
    },
  })

  const configs = configsQuery.data || []
  const runs = runsQuery.data || []

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Lead Sources</h2>
          <p className="text-sm text-slate-500 mt-1">Sources feeding leads into this campaign. Manage schedules and trigger runs.</p>
        </div>
        <Link
          to="/lead-sources"
          className="flex items-center gap-2 text-xs font-semibold text-sky-600 hover:text-sky-700"
        >
          Manage all sources <ChevronRight size={13} />
        </Link>
      </div>

      {configsQuery.isLoading ? (
        <div className="text-sm text-slate-400">Loading…</div>
      ) : configs.length === 0 ? (
        <div className="rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 p-8 text-center">
          <p className="text-sm text-slate-500 mb-3">No lead sources configured for this campaign yet.</p>
          <Link to="/lead-sources" className="text-sm font-semibold text-sky-600 hover:text-sky-700">
            Add one →
          </Link>
        </div>
      ) : (
        <div className="space-y-2">
          {configs.map(cfg => (
            <div key={cfg.id} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg flex-shrink-0 bg-indigo-50">
                <Database size={14} className="text-indigo-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-slate-900">{cfg.label ?? cfg.source_display_name}</span>
                  {!cfg.source_available && <span className="text-[10px] font-bold uppercase text-rose-500">Not configured</span>}
                  {cfg.cron_schedule && (
                    <span className="inline-flex items-center gap-1 text-[10px] text-emerald-600">
                      <Clock size={10} /> scheduled
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  {cfg.last_run_at ? `Last run ${new Date(cfg.last_run_at).toLocaleString()}` : 'Never run'}
                </p>
              </div>
              <button
                onClick={() => { setRunningId(cfg.id); runMutation.mutate(cfg.id) }}
                disabled={runningId === cfg.id || !cfg.source_available}
                className="btn-tactile flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
              >
                {runningId === cfg.id ? 'Running…' : 'Run now'}
              </button>
            </div>
          ))}
        </div>
      )}

      <div>
        <h3 className="text-sm font-semibold text-slate-900 mb-3">Recent Runs</h3>
        {runs.length === 0 ? (
          <div className="text-sm text-slate-400">No runs yet.</div>
        ) : (
          <div className="space-y-1">
            {runs.map(r => (
              <div key={r.id} className="flex items-center gap-3 rounded-lg bg-slate-50 px-3 py-2 text-xs">
                <span className="font-mono text-slate-400 w-20 truncate">{r.source_type}</span>
                <span className={`font-semibold ${
                  r.status === 'done' ? 'text-emerald-600' :
                  r.status === 'failed' ? 'text-rose-600' :
                  r.status === 'running' ? 'text-sky-600' : 'text-slate-500'
                }`}>{r.status}</span>
                <span className="text-slate-500">
                  {r.leads_added}/{r.leads_found} new
                </span>
                {r.triggered_by && (
                  <span className="text-[10px] uppercase tracking-wider text-slate-400">{r.triggered_by}</span>
                )}
                <span className="ml-auto text-slate-400">{new Date(r.started_at).toLocaleString()}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
