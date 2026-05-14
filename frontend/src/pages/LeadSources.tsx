import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusCircle, Play, Loader2, CheckCircle2, AlertCircle, Database, ChevronDown, ChevronUp, Trash2, Clock, Plus, Globe } from 'lucide-react'
import { clsx } from 'clsx'

import { api } from '../api/client'
import Badge from '../components/Badge'
import { useToast } from '../components/Toast'
import { Campaign } from '../hooks/useCampaigns'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Modal from '../components/Modal'
import { FilterBar, Select } from '../components/FilterBar'

// ── Types ─────────────────────────────────────────────────────────────────────

interface LeadSource {
  source_type: string
  display_name: string
  description: string
  available: boolean
  config_schema: {
    properties: Record<string, {
      type: string
      title: string
      description?: string
      default?: unknown
      enum?: string[]
      items?: { type: string; enum?: string[] }
    }>
    required?: string[]
  }
}

interface LeadGenConfig {
  id: string
  campaign_id: string
  source_type: string
  source_display_name: string
  source_available: boolean
  config: Record<string, unknown>
  label: string | null
  is_enabled: boolean
  cron_schedule: string | null
  last_run_at: string | null
  created_at: string
}

const CRON_PRESETS: { label: string; value: string }[] = [
  { label: 'Manual only', value: '' },
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily at 9am', value: '0 9 * * *' },
  { label: 'Weekdays 9am', value: '0 9 * * 1-5' },
  { label: 'Weekly (Mon 9am)', value: '0 9 * * 1' },
]

interface LeadGenRun {
  id: string
  config_id: string
  source_type: string
  status: 'pending' | 'running' | 'done' | 'failed'
  leads_found: number
  leads_added: number
  started_at: string
  finished_at: string | null
  error: string | null
}

const runStatusVariant: Record<LeadGenRun['status'], 'neutral' | 'info' | 'success' | 'danger'> = {
  pending: 'neutral',
  running: 'info',
  done: 'success',
  failed: 'danger',
}

const SOURCE_COLOURS: Record<string, { bg: string; text: string; border: string }> = {
  apify_jobs:  { bg: 'bg-orange-50',  text: 'text-orange-600', border: 'border-orange-200' },
  apollo:      { bg: 'bg-indigo-50',  text: 'text-indigo-600', border: 'border-indigo-200' },
  hunter:      { bg: 'bg-amber-50',   text: 'text-amber-600',  border: 'border-amber-200' },
  proxycurl:   { bg: 'bg-brand-50',     text: 'text-brand-600',    border: 'border-brand-200' },
  github:      { bg: 'bg-slate-50',   text: 'text-slate-700',  border: 'border-slate-300' },
}
const DEFAULT_COLOUR = { bg: 'bg-brand-50', text: 'text-brand-600', border: 'border-brand-200' }

// ── Schema-driven config form ─────────────────────────────────────────────────

interface SchemaFormProps {
  schema: LeadSource['config_schema']
  value: Record<string, unknown>
  onChange: (v: Record<string, unknown>) => void
}

function SchemaForm({ schema, value, onChange }: SchemaFormProps) {
  function set(key: string, v: unknown) {
    onChange({ ...value, [key]: v })
  }

  const inputCls = "w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-900 outline-none transition focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:border-slate-800 dark:bg-slate-900 dark:text-white dark:focus:ring-brand-900/20"
  const labelCls = "mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400"

  return (
    <div className="space-y-5">
      {Object.entries(schema.properties).map(([key, field]) => {
        const current = value[key] ?? field.default ?? ''
        const required = schema.required?.includes(key)

        if (field.type === 'array' && field.items?.enum) {
          const selected = (current as string[]) || []
          return (
            <div key={key}>
              <label className={labelCls}>
                {field.title}{required && <span className="text-rose-500 ml-1">*</span>}
              </label>
              {field.description && <p className="mb-2 text-[10px] font-medium text-slate-400">{field.description}</p>}
              <div className="flex flex-wrap gap-3">
                {field.items!.enum!.map(opt => (
                  <label key={opt} className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                      checked={selected.includes(opt)}
                      onChange={e => {
                        const next = e.target.checked
                          ? [...selected, opt]
                          : selected.filter(s => s !== opt)
                        set(key, next)
                      }}
                    />
                    <span className="text-xs font-semibold text-slate-700 dark:text-slate-300">{opt}</span>
                  </label>
                ))}
              </div>
            </div>
          )
        }

        if (field.type === 'array') {
          const asString = Array.isArray(current) ? (current as string[]).join(', ') : String(current)
          return (
            <div key={key}>
              <label className={labelCls}>
                {field.title}{required && <span className="text-rose-500 ml-1">*</span>}
              </label>
              {field.description && <p className="mb-2 text-[10px] font-medium text-slate-400">{field.description}</p>}
              <textarea
                rows={2}
                value={asString}
                onChange={e => set(key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                className={clsx(inputCls, "resize-none h-auto py-3")}
                placeholder="Comma-separated values"
              />
            </div>
          )
        }

        if (field.type === 'boolean') {
          return (
            <div key={key} className="flex items-center gap-3">
              <input
                type="checkbox"
                id={key}
                className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                checked={Boolean(current)}
                onChange={e => set(key, e.target.checked)}
              />
              <label htmlFor={key} className="text-sm font-semibold text-slate-700 dark:text-slate-300">{field.title}</label>
              {field.description && <span className="text-[10px] font-medium text-slate-400">({field.description})</span>}
            </div>
          )
        }

        if (field.type === 'integer') {
          return (
            <div key={key}>
              <label className={labelCls}>{field.title}</label>
              {field.description && <p className="mb-2 text-[10px] font-medium text-slate-400">{field.description}</p>}
              <input
                type="number"
                value={Number(current)}
                onChange={e => set(key, parseInt(e.target.value, 10))}
                className={clsx(inputCls, "w-32")}
              />
            </div>
          )
        }

        if (field.enum) {
          return (
            <div key={key}>
              <label className={labelCls}>{field.title}</label>
              <select
                value={String(current)}
                onChange={e => set(key, e.target.value)}
                className={inputCls}
              >
                {field.enum.map(opt => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </div>
          )
        }

        return (
          <div key={key}>
            <label className={labelCls}>
              {field.title}{required && <span className="text-rose-500 ml-1">*</span>}
            </label>
            {field.description && <p className="mb-2 text-[10px] font-medium text-slate-400">{field.description}</p>}
            <input
              type="text"
              value={String(current)}
              onChange={e => set(key, e.target.value)}
              className={inputCls}
              placeholder={String(field.default ?? '')}
            />
          </div>
        )
      })}
    </div>
  )
}

// ── Create config modal ───────────────────────────────────────────────────────

function CreateConfigModal({ open, campaignId, sources, onClose, onSubmit, isLoading }: {
  open: boolean
  campaignId: string
  sources: LeadSource[]
  onClose: () => void
  onSubmit: (data: { campaign_id: string; source_type: string; config: Record<string, unknown>; label?: string }) => void
  isLoading: boolean
}) {
  const [selectedSource, setSelectedSource] = useState(sources[0]?.source_type ?? '')
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [label, setLabel] = useState('')

  const source = sources.find(s => s.source_type === selectedSource)

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSubmit({
      campaign_id: campaignId,
      source_type: selectedSource,
      config: configValues,
      label: label.trim() || undefined,
    })
  }

  const inputCls = "w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 outline-none transition focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:border-slate-800 dark:bg-slate-900 dark:text-white dark:focus:ring-brand-900/20"
  const labelCls = "mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400"

  return (
    <Modal title="Configure Lead Source" open={open} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className={labelCls}>Select Source Provider</label>
          <div className="grid gap-2">
            {sources.map(src => {
              const colour = SOURCE_COLOURS[src.source_type] ?? DEFAULT_COLOUR
              const active = selectedSource === src.source_type
              return (
                <button
                  key={src.source_type}
                  type="button"
                  onClick={() => { setSelectedSource(src.source_type); setConfigValues({}) }}
                  className={clsx(
                    'flex items-center gap-4 p-4 rounded-xl border text-left transition-all',
                    active
                      ? 'border-brand-500 bg-brand-50/50 dark:bg-brand-900/10'
                      : 'border-slate-200 hover:border-slate-300 dark:border-slate-800'
                  )}
                >
                  <div className={clsx('flex items-center justify-center w-10 h-10 rounded-xl shrink-0', colour.bg)}>
                    <Database size={18} className={colour.text} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-slate-900 dark:text-white">{src.display_name}</span>
                      {src.available ? <CheckCircle2 size={12} className="text-emerald-500" /> : <Badge label="No Key" variant="danger" size="xs" />}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1 line-clamp-1">{src.description}</p>
                  </div>
                </button>
              )
            })}
          </div>
        </div>

        <div>
          <label className={labelCls}>Source Label (Internal)</label>
          <input
            type="text"
            value={label}
            onChange={e => setLabel(e.target.value)}
            placeholder="e.g. Sales Navigator Export"
            className={inputCls}
          />
        </div>

        {source && (
          <div className="pt-4 border-t border-slate-100 dark:border-slate-800">
            <label className={labelCls}>Provider Configuration</label>
            <div className="mt-4">
              <SchemaForm
                schema={source.config_schema}
                value={configValues}
                onChange={setConfigValues}
              />
            </div>
          </div>
        )}

        <div className="flex justify-end gap-3 pt-6 border-t border-slate-100 dark:border-slate-800">
          <Button variant="secondary" size="md" onClick={onClose} disabled={isLoading}>Cancel</Button>
          <Button type="submit" variant="primary" size="md" isLoading={isLoading} disabled={!selectedSource}>Create Configuration</Button>
        </div>
      </form>
    </Modal>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function LeadSources() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [selectedCampaignId, setSelectedCampaignId] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [runningConfigId, setRunningConfigId] = useState<string | null>(null)

  const { data: campaigns, isLoading: campaignsLoading } = useQuery<Campaign[]>({
    queryKey: ['campaigns'],
    queryFn: () => api.get('/campaigns').then(r => r.data),
  })

  const { data: sources } = useQuery<LeadSource[]>({
    queryKey: ['lead-gen-sources'],
    queryFn: () => api.get('/lead-gen/sources').then(r => r.data),
  })

  const { data: configs, isLoading: configsLoading } = useQuery<LeadGenConfig[]>({
    queryKey: ['lead-gen-configs', selectedCampaignId],
    queryFn: () => api.get(`/lead-gen/configs/${selectedCampaignId}`).then(r => r.data),
    enabled: !!selectedCampaignId,
  })

  const createMutation = useMutation({
    mutationFn: (data: Parameters<typeof api.post>[1]) =>
      api.post('/lead-gen/configs', data).then(r => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lead-gen-configs', selectedCampaignId] })
      setShowCreateModal(false)
      toast.success('Lead source config created')
    },
    onError: () => toast.error('Failed to create config'),
  })

  const deleteMutation = useMutation({
    mutationFn: (configId: string) => api.delete(`/lead-gen/configs/${configId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lead-gen-configs', selectedCampaignId] })
      toast.success('Configuration deleted')
    },
    onError: () => toast.error('Failed to delete config'),
  })

  const runMutation = useMutation({
    mutationFn: (configId: string) =>
      api.post('/lead-gen/trigger', {
        campaign_id: selectedCampaignId,
        config_id: configId,
      }).then(r => r.data),
    onSuccess: (data, configId) => {
      setRunningConfigId(null)
      toast.success('Source run triggered')
      queryClient.invalidateQueries({ queryKey: ['lead-gen-runs', configId] })
    },
    onError: (err: unknown) => {
      setRunningConfigId(null)
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Failed to start run')
    },
  })

  useEffect(() => {
    if (campaigns && campaigns.length > 0 && !selectedCampaignId) {
      setSelectedCampaignId(campaigns[0].id)
    }
  }, [campaigns, selectedCampaignId])

  return (
    <div className="space-y-6 pb-12">
      <PageHeader
        screenLabel="Lead Gen"
        eyebrow="Lead Sources"
        title="Lead Sources"
        description="Connect and manage external databases and scrapers to feed leads directly into your campaigns."
        actions={
          <Button
            variant="primary"
            size="md"
            icon={Plus}
            disabled={!selectedCampaignId}
            onClick={() => setShowCreateModal(true)}
          >
            New Source
          </Button>
        }
      />

      {sources && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {sources.map(src => {
            const colour = SOURCE_COLOURS[src.source_type] ?? DEFAULT_COLOUR
            return (
              <Card 
                key={src.source_type} 
                padding="md" 
                className={clsx(
                  'group transition-all hover:scale-[1.02] active:scale-[0.98]',
                  !src.available && "opacity-60 grayscale"
                )}
              >
                <div className="flex flex-col gap-4">
                  <div className="flex items-center justify-between">
                    <div className={clsx('flex h-12 w-12 items-center justify-center rounded-2xl shadow-sm', colour.bg)}>
                      <Database size={20} className={colour.text} />
                    </div>
                    {src.available ? (
                      <div className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-50 text-emerald-500 dark:bg-emerald-900/20">
                        <CheckCircle2 size={14} />
                      </div>
                    ) : (
                      <Badge label="Needs Key" variant="danger" size="xs" />
                    )}
                  </div>
                  <div>
                    <h4 className="text-sm font-bold text-slate-900 dark:text-white">{src.display_name}</h4>
                    <p className="mt-1 text-[11px] font-medium text-slate-500 leading-relaxed">{src.description}</p>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      <FilterBar>
        <div className="flex items-center gap-3">
          <label className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Campaign</label>
          <Select 
            value={selectedCampaignId} 
            onChange={setSelectedCampaignId}
            className="w-64"
          >
            {!selectedCampaignId && <option value="">Select campaign...</option>}
            {campaigns?.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </div>
      </FilterBar>

      <div className="space-y-4">
        {configsLoading ? (
          <div className="space-y-4">{[0,1,2].map(i => <div key={i} className="h-24 skeleton rounded-2xl" />)}</div>
        ) : configs && configs.length > 0 ? (
          <div className="grid gap-3">
            {configs.map(cfg => (
              <ConfigCard
                key={cfg.id}
                config={cfg}
                onRun={id => { setRunningConfigId(id); runMutation.mutate(id); }}
                onDelete={id => { if (confirm('Remove this lead source?')) deleteMutation.mutate(id) }}
                isRunning={runningConfigId === cfg.id}
              />
            ))}
          </div>
        ) : selectedCampaignId ? (
          <Card padding="lg">
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-slate-50 dark:bg-slate-900">
                <Database size={24} className="text-slate-300" />
              </div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">No sources connected</h3>
              <p className="mt-1 text-sm text-slate-500">Connect a lead source provider to start importing prospects automatically.</p>
              <Button 
                variant="primary" 
                size="sm" 
                className="mt-6" 
                icon={Plus}
                onClick={() => setShowCreateModal(true)}
              >
                Connect Source
              </Button>
            </div>
          </Card>
        ) : (
          <Card padding="lg">
            <div className="flex flex-col items-center justify-center py-12 text-center text-slate-400">
              <Globe size={32} strokeWidth={1.5} />
              <p className="mt-4 text-sm font-medium">Select a campaign to manage lead sources</p>
            </div>
          </Card>
        )}
      </div>

      {showCreateModal && selectedCampaignId && sources && (
        <CreateConfigModal
          open={showCreateModal}
          campaignId={selectedCampaignId}
          sources={sources}
          onClose={() => setShowCreateModal(false)}
          onSubmit={data => createMutation.mutate(data)}
          isLoading={createMutation.isPending}
        />
      )}
    </div>
  )
}

function ConfigCard({ config, onRun, onDelete, isRunning }: {
  config: LeadGenConfig
  onRun: (id: string) => void
  onDelete: (id: string) => void
  isRunning: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const colour = SOURCE_COLOURS[config.source_type] ?? DEFAULT_COLOUR
  const queryClient = useQueryClient()
  const toast = useToast()

  const scheduleMutation = useMutation({
    mutationFn: (cron_schedule: string) =>
      api.patch(`/lead-gen/configs/${config.id}`, { cron_schedule }).then(r => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['lead-gen-configs', config.campaign_id] })
      toast.success('Schedule updated')
    },
    onError: () => toast.error('Failed to update schedule'),
  })

  const currentPreset = CRON_PRESETS.find(p => p.value === (config.cron_schedule ?? ''))

  return (
    <Card padding="none" className={clsx('overflow-hidden border-l-4', colour.border)}>
      <div className="p-5">
        <div className="flex items-center gap-4">
          <div className={clsx('flex h-10 w-10 items-center justify-center rounded-xl shrink-0', colour.bg)}>
            <Database size={18} className={colour.text} />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold text-slate-900 dark:text-white truncate">
                {config.label ?? config.source_display_name}
              </span>
              <Badge label={config.source_display_name} variant="neutral" size="xs" />
              {!config.source_available && <Badge label="Not Configured" variant="danger" size="xs" />}
            </div>
            <div className="mt-1 flex items-center gap-3">
              <p className="text-[11px] font-medium text-slate-400">Created {new Date(config.created_at).toLocaleDateString()}</p>
              {config.cron_schedule && (
                <div className="flex items-center gap-1.5 text-[11px] font-bold text-brand-600">
                  <Clock size={11} /> {currentPreset?.label ?? 'Custom Schedule'}
                </div>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="secondary"
              size="xs"
              icon={expanded ? ChevronUp : ChevronDown}
              onClick={() => setExpanded(!expanded)}
            />
            <Button
              variant="danger"
              size="xs"
              icon={Trash2}
              onClick={() => onDelete(config.id)}
            />
            <Button
              variant="primary"
              size="sm"
              icon={isRunning ? undefined : Play}
              isLoading={isRunning}
              disabled={!config.source_available}
              onClick={() => onRun(config.id)}
            >
              Run
            </Button>
          </div>
        </div>

        {expanded && (
          <div className="mt-5 space-y-6 border-t border-slate-100 pt-5 dark:border-slate-800">
            <div>
              <label className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-slate-400">Automation Schedule</label>
              <div className="flex items-center gap-4">
                <Select
                  value={config.cron_schedule ?? ''}
                  onChange={v => scheduleMutation.mutate(v)}
                  disabled={scheduleMutation.isPending}
                  className="w-64"
                >
                  {CRON_PRESETS.map(p => <option key={p.value} value={p.value}>{p.label}</option>)}
                </Select>
                {config.last_run_at && (
                  <span className="text-[11px] font-medium text-slate-400 italic">
                    Last execution: {new Date(config.last_run_at).toLocaleString()}
                  </span>
                )}
              </div>
            </div>
            <div>
              <label className="mb-2 block text-[10px] font-bold uppercase tracking-widest text-slate-400">Recent Execution History</label>
              <RunHistory configId={config.id} />
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

function RunHistory({ configId }: { configId: string }) {
  const { data: runs, isLoading } = useQuery<LeadGenRun[]>({
    queryKey: ['lead-gen-runs', configId],
    queryFn: () => api.get('/lead-gen/runs', { params: { config_id: configId } }).then(r => r.data),
  })

  if (isLoading) return <div className="flex justify-center py-6"><Loader2 size={14} className="animate-spin text-slate-300" /></div>
  if (!runs?.length) return <p className="py-4 text-center text-xs text-slate-400">No previous runs recorded</p>

  return (
    <div className="overflow-hidden rounded-xl border border-slate-100 dark:border-slate-800">
      <table className="w-full text-xs text-left">
        <thead className="bg-slate-50 dark:bg-slate-900/50">
          <tr>
            <th className="px-4 py-2 font-bold text-slate-400 uppercase tracking-widest text-[9px]">Status</th>
            <th className="px-4 py-2 font-bold text-slate-400 uppercase tracking-widest text-[9px]">Success</th>
            <th className="px-4 py-2 font-bold text-slate-400 uppercase tracking-widest text-[9px]">Timestamp</th>
            <th className="px-4 py-2 font-bold text-slate-400 uppercase tracking-widest text-[9px]">Outcome</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
          {runs.map(run => (
            <tr key={run.id}>
              <td className="px-4 py-2">
                <Badge label={run.status} variant={runStatusVariant[run.status]} size="xs" />
              </td>
              <td className="px-4 py-2">
                <div className="flex items-center gap-1.5">
                  <span className="font-bold text-slate-700 dark:text-slate-300">{run.leads_found} found</span>
                  <span className="font-bold text-emerald-600">+{run.leads_added} added</span>
                </div>
              </td>
              <td className="px-4 py-2 text-slate-400 font-medium tabular-nums">
                {new Date(run.started_at).toLocaleString()}
              </td>
              <td className="px-4 py-2">
                {run.error ? <span className="text-rose-500 font-medium truncate max-w-[150px] block" title={run.error}>{run.error}</span> : <span className="text-slate-300">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
