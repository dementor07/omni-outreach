import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Database, ChevronRight, Clock, Play, Plus } from 'lucide-react'
import { api } from '../../../../api/client'
import { useToast } from '../../../../components/Toast'
import Button from '../../../../components/Button'
import Badge from '../../../../components/Badge'
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
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Lead Sources</h2>
          <p className="text-sm text-slate-500 mt-1">Sources feeding leads into this campaign. Manage schedules and trigger runs.</p>
        </div>
        <Link
          to="/lead-sources"
          className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wider text-brand-600 hover:text-brand-700 transition-colors"
        >
          Manage all sources <ChevronRight size={14} />
        </Link>
      </div>

      {configsQuery.isLoading ? (
        <div className="flex items-center justify-center py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-brand-500" />
        </div>
      ) : configs.length === 0 ? (
        <div className="rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 p-8 text-center dark:border-slate-800 dark:bg-slate-900/50">
          <p className="text-sm text-slate-500 mb-4">No lead sources configured for this campaign yet.</p>
          <Button variant="secondary" size="sm" icon={Plus} onClick={() => {}}>
            Configure source
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {configs.map(cfg => (
            <div key={cfg.id} className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl flex-shrink-0 bg-brand-50 text-brand-600 dark:bg-brand-900/30 dark:text-brand-400">
                <Database size={18} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-semibold text-slate-900 dark:text-white">{cfg.label ?? cfg.source_display_name}</span>
                  {!cfg.source_available && <Badge label="Not configured" variant="danger" size="xs" />}
                  {cfg.cron_schedule && (
                    <span className="inline-flex items-center gap-1 text-[11px] font-medium text-emerald-600">
                      <Clock size={12} /> scheduled
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-400 mt-0.5">
                  {cfg.last_run_at ? `Last run ${new Date(cfg.last_run_at).toLocaleString()}` : 'Never run'}
                </p>
              </div>
              <Button
                variant="primary"
                size="sm"
                icon={Play}
                isLoading={runningId === cfg.id}
                disabled={!cfg.source_available}
                onClick={() => { setRunningId(cfg.id); runMutation.mutate(cfg.id) }}
              >
                Run now
              </Button>
            </div>
          ))}
        </div>
      )}

      <div>
        <h3 className="text-xs font-bold uppercase tracking-widest text-slate-400 mb-4">Recent Runs</h3>
        {runs.length === 0 ? (
          <div className="py-8 text-center text-sm text-slate-400 border border-slate-100 rounded-xl border-dashed">No runs yet.</div>
        ) : (
          <div className="space-y-2">
            {runs.map(r => (
              <div key={r.id} className="flex items-center gap-4 rounded-xl border border-slate-100 bg-slate-50/50 px-4 py-3 text-[13px] dark:border-slate-800 dark:bg-slate-800/20">
                <div className="w-20 shrink-0 font-mono text-[11px] font-bold uppercase tracking-tight text-slate-400">{r.source_type}</div>
                <Badge label={r.status} asStatus size="xs" dot />
                <div className="flex items-center gap-1.5 text-slate-500 font-medium">
                  <span className="text-slate-900 dark:text-slate-200">{r.leads_added}</span>
                  <span className="text-slate-300">/</span>
                  <span>{r.leads_found} leads</span>
                </div>
                {r.triggered_by && (
                  <div className="px-2 py-0.5 rounded bg-slate-100 text-[10px] font-bold uppercase text-slate-500 dark:bg-slate-800">
                    {r.triggered_by}
                  </div>
                )}
                <div className="ml-auto tabular-nums text-slate-400 text-xs">
                  {new Date(r.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
