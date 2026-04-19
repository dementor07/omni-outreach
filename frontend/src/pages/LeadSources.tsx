import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusCircle, Play, Loader2, CheckCircle2, AlertCircle, Database, ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { clsx } from 'clsx'

import { api } from '../api/client'
import Badge from '../components/Badge'
import { useToast } from '../components/Toast'
import { Campaign } from '../hooks/useCampaigns'

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
  created_at: string
}

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

// ── Status badge map ──────────────────────────────────────────────────────────

const runStatusVariant: Record<LeadGenRun['status'], 'muted' | 'info' | 'success' | 'error'> = {
  pending: 'muted',
  running: 'info',
  done: 'success',
  failed: 'error',
}

// ── Source icon colour ────────────────────────────────────────────────────────

const SOURCE_COLOURS: Record<string, { bg: string; text: string; border: string }> = {
  apify_jobs:  { bg: 'bg-orange-50',  text: 'text-orange-600', border: 'border-orange-200' },
  apollo:      { bg: 'bg-indigo-50',  text: 'text-indigo-600', border: 'border-indigo-200' },
  hunter:      { bg: 'bg-amber-50',   text: 'text-amber-600',  border: 'border-amber-200' },
  proxycurl:   { bg: 'bg-sky-50',     text: 'text-sky-600',    border: 'border-sky-200' },
  github:      { bg: 'bg-slate-50',   text: 'text-slate-700',  border: 'border-slate-300' },
}
const DEFAULT_COLOUR = { bg: 'bg-violet-50', text: 'text-violet-600', border: 'border-violet-200' }

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

  return (
    <div className="space-y-4">
      {Object.entries(schema.properties).map(([key, field]) => {
        const current = value[key] ?? field.default ?? ''
        const required = schema.required?.includes(key)

        if (field.type === 'array' && field.items?.enum) {
          // Multi-select checkboxes
          const selected = (current as string[]) || []
          return (
            <div key={key}>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                {field.title}{required && <span className="text-rose-500 ml-0.5">*</span>}
              </label>
              {field.description && (
                <p className="text-[11px] text-slate-400 mb-1">{field.description}</p>
              )}
              <div className="flex flex-wrap gap-2">
                {field.items!.enum!.map(opt => (
                  <label key={opt} className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      className="rounded border-slate-300"
                      checked={selected.includes(opt)}
                      onChange={e => {
                        const next = e.target.checked
                          ? [...selected, opt]
                          : selected.filter(s => s !== opt)
                        set(key, next)
                      }}
                    />
                    <span className="text-xs text-slate-600">{opt}</span>
                  </label>
                ))}
              </div>
            </div>
          )
        }

        if (field.type === 'array') {
          // Array of strings — comma-separated input
          const asString = Array.isArray(current) ? (current as string[]).join(', ') : String(current)
          return (
            <div key={key}>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                {field.title}{required && <span className="text-rose-500 ml-0.5">*</span>}
              </label>
              {field.description && (
                <p className="text-[11px] text-slate-400 mb-1">{field.description}</p>
              )}
              <textarea
                rows={2}
                value={asString}
                onChange={e => set(key, e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 resize-none"
                placeholder="Comma-separated values"
              />
            </div>
          )
        }

        if (field.type === 'boolean') {
          return (
            <div key={key} className="flex items-center gap-2">
              <input
                type="checkbox"
                id={key}
                className="rounded border-slate-300"
                checked={Boolean(current)}
                onChange={e => set(key, e.target.checked)}
              />
              <label htmlFor={key} className="text-sm text-slate-700">{field.title}</label>
              {field.description && (
                <span className="text-[11px] text-slate-400">({field.description})</span>
              )}
            </div>
          )
        }

        if (field.type === 'integer') {
          return (
            <div key={key}>
              <label className="block text-xs font-semibold text-slate-700 mb-1">{field.title}</label>
              {field.description && (
                <p className="text-[11px] text-slate-400 mb-1">{field.description}</p>
              )}
              <input
                type="number"
                value={Number(current)}
                onChange={e => set(key, parseInt(e.target.value, 10))}
                className="w-32 border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
              />
            </div>
          )
        }

        if (field.enum) {
          return (
            <div key={key}>
              <label className="block text-xs font-semibold text-slate-700 mb-1">{field.title}</label>
              <select
                value={String(current)}
                onChange={e => set(key, e.target.value)}
                className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 bg-white"
              >
                {field.enum.map(opt => (
                  <option key={opt} value={opt}>{opt}</option>
                ))}
              </select>
            </div>
          )
        }

        // Default: text input
        return (
          <div key={key}>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              {field.title}{required && <span className="text-rose-500 ml-0.5">*</span>}
            </label>
            {field.description && (
              <p className="text-[11px] text-slate-400 mb-1">{field.description}</p>
            )}
            <input
              type="text"
              value={String(current)}
              onChange={e => set(key, e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
              placeholder={String(field.default ?? '')}
            />
          </div>
        )
      })}
    </div>
  )
}

// ── Create config modal ───────────────────────────────────────────────────────

interface CreateConfigModalProps {
  campaignId: string
  sources: LeadSource[]
  onClose: () => void
  onSubmit: (data: { campaign_id: string; source_type: string; config: Record<string, unknown>; label?: string }) => void
  isLoading: boolean
}

function CreateConfigModal({ campaignId, sources, onClose, onSubmit, isLoading }: CreateConfigModalProps) {
  const [selectedSource, setSelectedSource] = useState(sources[0]?.source_type ?? '')
  const [configValues, setConfigValues] = useState<Record<string, unknown>>({})
  const [label, setLabel] = useState('')

  const source = sources.find(s => s.source_type === selectedSource)

  function handleSubmit() {
    onSubmit({
      campaign_id: campaignId,
      source_type: selectedSource,
      config: configValues,
      label: label.trim() || undefined,
    })
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-start justify-center z-50 pt-16 px-4 overflow-y-auto">
      <div className="bg-white rounded-xl w-full max-w-lg shadow-xl mb-10">
        <div className="px-6 pt-6 pb-4 border-b border-slate-100">
          <h2 className="text-base font-semibold text-slate-900">New Lead Source Config</h2>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Source selector */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-2">Source</label>
            <div className="grid grid-cols-1 gap-2">
              {sources.map(src => {
                const colour = SOURCE_COLOURS[src.source_type] ?? DEFAULT_COLOUR
                return (
                  <button
                    key={src.source_type}
                    onClick={() => { setSelectedSource(src.source_type); setConfigValues({}) }}
                    className={clsx(
                      'flex items-start gap-3 p-3 rounded-lg border text-left transition-all',
                      selectedSource === src.source_type
                        ? `${colour.bg} ${colour.border} ring-2 ring-inset ${colour.text.replace('text-', 'ring-')}`
                        : 'border-slate-200 hover:border-slate-300',
                    )}
                  >
                    <div className={clsx('mt-0.5 flex items-center justify-center w-6 h-6 rounded-md flex-shrink-0', colour.bg)}>
                      <Database size={12} className={colour.text} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900">{src.display_name}</span>
                        {src.available
                          ? <CheckCircle2 size={12} className="text-emerald-500 flex-shrink-0" />
                          : <AlertCircle size={12} className="text-amber-400 flex-shrink-0" />
                        }
                      </div>
                      <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{src.description}</p>
                      {!src.available && (
                        <p className="text-[11px] text-amber-600 mt-1 font-medium">API key not configured — add in Settings</p>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Label */}
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">Label (optional)</label>
            <input
              type="text"
              value={label}
              onChange={e => setLabel(e.target.value)}
              placeholder="e.g. US SaaS CEOs"
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
            />
          </div>

          {/* Source-specific config */}
          {source && (
            <div>
              <p className="text-xs font-semibold text-slate-700 mb-3">Configuration</p>
              <SchemaForm
                schema={source.config_schema}
                value={configValues}
                onChange={setConfigValues}
              />
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-100">
          <button onClick={onClose} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-900 transition-colors">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!selectedSource || isLoading}
            className="px-4 py-2 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700 disabled:opacity-50 transition-colors"
          >
            {isLoading ? 'Creating…' : 'Create Config'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Run history ───────────────────────────────────────────────────────────────

function RunHistory({ configId }: { configId: string }) {
  const { data: runs, isLoading } = useQuery<LeadGenRun[]>({
    queryKey: ['lead-gen-runs', configId],
    queryFn: () => api.get('/lead-gen/runs', { params: { config_id: configId } }).then(r => r.data),
  })

  if (isLoading) return <div className="flex items-center justify-center py-4"><Loader2 size={14} className="animate-spin text-slate-300" /></div>
  if (!runs?.length) return <p className="text-xs text-slate-400 py-3 text-center">No runs yet</p>

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-[10px] uppercase tracking-widest text-slate-400 border-b border-slate-100">
          <th className="pb-1 text-left font-medium">Status</th>
          <th className="pb-1 text-left font-medium">Found</th>
          <th className="pb-1 text-left font-medium">Added</th>
          <th className="pb-1 text-left font-medium">Started</th>
          <th className="pb-1 text-left font-medium">Error</th>
        </tr>
      </thead>
      <tbody>
        {runs.map(run => (
          <tr key={run.id} className="border-b border-slate-50 last:border-0">
            <td className="py-1.5 pr-3">
              <Badge variant={runStatusVariant[run.status]} label={run.status} />
            </td>
            <td className="py-1.5 pr-3 text-slate-700 font-medium">{run.leads_found}</td>
            <td className="py-1.5 pr-3 text-emerald-600 font-semibold">{run.leads_added}</td>
            <td className="py-1.5 pr-3 text-slate-400">
              {new Date(run.started_at).toLocaleString()}
            </td>
            <td className="py-1.5 text-rose-500 truncate max-w-[160px]" title={run.error ?? ''}>
              {run.error ?? '—'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

// ── Config card ───────────────────────────────────────────────────────────────

interface ConfigCardProps {
  config: LeadGenConfig
  onRun: (id: string) => void
  onDelete: (id: string) => void
  isRunning: boolean
}

function ConfigCard({ config, onRun, onDelete, isRunning }: ConfigCardProps) {
  const [expanded, setExpanded] = useState(false)
  const colour = SOURCE_COLOURS[config.source_type] ?? DEFAULT_COLOUR

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3">
        <div className={clsx('flex items-center justify-center w-8 h-8 rounded-lg flex-shrink-0', colour.bg)}>
          <Database size={14} className={colour.text} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-slate-900">
              {config.label ?? config.source_display_name}
            </span>
            <Badge variant={config.source_type === 'apify_jobs' ? 'info' : 'muted'} label={config.source_display_name} />
            {!config.source_available && (
              <Badge variant="error" label="Not configured" />
            )}
          </div>
          <p className="text-xs text-slate-400 mt-0.5">
            Created {new Date(config.created_at).toLocaleDateString()}
          </p>
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={() => setExpanded(e => !e)}
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-700 hover:bg-slate-50 transition-colors"
            title="View run history"
          >
            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          <button
            onClick={() => onDelete(config.id)}
            className="p-1.5 rounded-md text-slate-300 hover:text-rose-500 hover:bg-rose-50 transition-colors"
            title="Delete config"
          >
            <Trash2 size={14} />
          </button>
          <button
            onClick={() => onRun(config.id)}
            disabled={isRunning || !config.source_available}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors',
              config.source_available
                ? 'bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50'
                : 'bg-slate-100 text-slate-400 cursor-not-allowed',
            )}
          >
            {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Run
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-slate-100 px-4 py-3">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Run History</p>
          <RunHistory configId={config.id} />
        </div>
      )}
    </div>
  )
}

// ── Sources overview grid ─────────────────────────────────────────────────────

function SourcesGrid({ sources }: { sources: LeadSource[] }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
      {sources.map(src => {
        const colour = SOURCE_COLOURS[src.source_type] ?? DEFAULT_COLOUR
        return (
          <div
            key={src.source_type}
            className={clsx(
              'flex items-start gap-3 p-3 rounded-xl border',
              src.available ? `${colour.bg} ${colour.border}` : 'bg-slate-50 border-slate-200 opacity-60',
            )}
          >
            <div className={clsx('flex items-center justify-center w-8 h-8 rounded-lg flex-shrink-0 bg-white/70 ring-1', colour.border)}>
              <Database size={14} className={colour.text} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-slate-900">{src.display_name}</span>
                {src.available
                  ? <CheckCircle2 size={11} className="text-emerald-500" />
                  : <AlertCircle size={11} className="text-amber-400" />
                }
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5 leading-relaxed line-clamp-2">{src.description}</p>
              {!src.available && (
                <span className="text-[10px] text-amber-600 font-semibold">Needs API key</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

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
      toast.success('Config deleted')
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
      toast.success(`Run started — ${data.source_type}`)
      queryClient.invalidateQueries({ queryKey: ['lead-gen-runs', configId] })
    },
    onError: (err: unknown) => {
      setRunningConfigId(null)
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg ?? 'Failed to start run')
    },
  })

  function handleRun(configId: string) {
    setRunningConfigId(configId)
    runMutation.mutate(configId)
  }

  if (campaignsLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 size={24} className="animate-spin text-slate-400" />
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Lead Sources</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Configure multi-source lead generation per campaign
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          disabled={!selectedCampaignId}
          className="flex items-center gap-2 px-4 py-2 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          <PlusCircle size={15} />
          New Config
        </button>
      </div>

      {/* Sources overview */}
      {sources && <SourcesGrid sources={sources} />}

      {/* Campaign selector */}
      <div className="mb-6">
        <label className="block text-xs font-semibold text-slate-700 mb-1.5">Campaign</label>
        <select
          value={selectedCampaignId}
          onChange={e => setSelectedCampaignId(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 bg-white w-72"
        >
          {!selectedCampaignId && <option value="">Select a campaign…</option>}
          {campaigns?.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </div>

      {/* Configs */}
      {!selectedCampaignId ? (
        <div className="text-center py-16 text-slate-400 text-sm">
          Select a campaign to view and configure lead sources
        </div>
      ) : configsLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 size={20} className="animate-spin text-slate-400" />
        </div>
      ) : configs && configs.length > 0 ? (
        <div className="space-y-3">
          {configs.map(cfg => (
            <ConfigCard
              key={cfg.id}
              config={cfg}
              onRun={handleRun}
              onDelete={id => deleteMutation.mutate(id)}
              isRunning={runningConfigId === cfg.id}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-16 text-slate-400 text-sm">
          No lead source configs yet.{' '}
          <button
            onClick={() => setShowCreateModal(true)}
            className="text-sky-600 hover:underline"
          >
            Create one
          </button>
        </div>
      )}

      {showCreateModal && selectedCampaignId && sources && (
        <CreateConfigModal
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
