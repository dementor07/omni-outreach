import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusCircle, Play, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'

import { api } from '../api/client'
import Badge from '../components/Badge'
import { useToast } from '../components/Toast'
import { Campaign } from '../hooks/useCampaigns'

// ── Types ─────────────────────────────────────────────────────────────────────

interface JobSearchConfig {
  id: string
  campaign_id: string
  keywords: string[]
  location: string
  roles: string[]
  is_active: boolean
  created_at: string
}

interface JobSearchRun {
  id: string
  config_id: string
  status: 'running' | 'done' | 'completed' | 'failed' | 'pending'
  leads_found: number
  started_at: string
  completed_at: string | null
  error_message: string | null
}

interface CreateConfigPayload {
  campaign_id: string
  keywords: string[]
  location: string
  roles: string[]
}

// ── Run status badge ──────────────────────────────────────────────────────────

const runStatusVariant: Partial<Record<JobSearchRun['status'], 'muted' | 'info' | 'success' | 'error'>> = {
  pending:   'muted',
  running:   'info',
  done:      'success',
  completed: 'success',
  failed:    'error',
}

// ── Create config modal ───────────────────────────────────────────────────────

interface CreateConfigModalProps {
  campaignId: string
  onClose: () => void
  onSubmit: (data: CreateConfigPayload) => void
  isLoading: boolean
}

function CreateConfigModal({ campaignId, onClose, onSubmit, isLoading }: CreateConfigModalProps) {
  const [keywords, setKeywords] = useState('')
  const [location, setLocation] = useState('')
  const [roles, setRoles] = useState('')

  function handleSubmit() {
    onSubmit({
      campaign_id: campaignId,
      keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
      location: location.trim(),
      roles: roles.split(',').map(r => r.trim()).filter(Boolean),
    })
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
        <h2 className="text-base font-semibold text-slate-900 mb-5">New Job Search Config</h2>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Keywords</label>
            <input
              type="text"
              value={keywords}
              onChange={e => setKeywords(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
              placeholder="e.g. software engineer, react developer"
            />
            <p className="text-xs text-slate-400 mt-1">Comma-separated</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Location</label>
            <input
              type="text"
              value={location}
              onChange={e => setLocation(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
              placeholder="e.g. San Francisco, CA"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Roles</label>
            <input
              type="text"
              value={roles}
              onChange={e => setRoles(e.target.value)}
              className="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500"
              placeholder="e.g. Frontend Engineer, Full Stack"
            />
            <p className="text-xs text-slate-400 mt-1">Comma-separated</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-6">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-slate-600 hover:text-slate-900 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!keywords.trim() || !location.trim() || isLoading}
            className="px-4 py-2 bg-sky-600 text-white text-sm rounded-lg hover:bg-sky-700 disabled:opacity-50 transition-colors"
          >
            {isLoading ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Run history panel ─────────────────────────────────────────────────────────

function RunHistoryPanel({ configId }: { configId: string }) {
  const { data: runs, isLoading } = useQuery<JobSearchRun[]>({
    queryKey: ['job-search-runs', configId],
    queryFn: () => api.get('/job-search/runs', { params: { config_id: configId } }).then(r => r.data),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-16">
        <Loader2 size={16} className="animate-spin text-slate-400" />
      </div>
    )
  }

  if (!runs || runs.length === 0) {
    return <p className="text-sm text-slate-400 py-3 text-center">No runs yet</p>
  }

  return (
    <div className="mt-3 border-t border-slate-100 pt-3 space-y-2">
      {runs.map(run => {
        const duration =
          run.completed_at && run.started_at
            ? Math.round(
                (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000,
              )
            : null
        return (
          <div key={run.id} className="flex items-center justify-between text-xs text-slate-500">
            <div className="flex items-center gap-2">
              <Badge label={run.status} variant={runStatusVariant[run.status] ?? 'muted'} />
              <span>{new Date(run.started_at).toLocaleString()}</span>
            </div>
            <div className="flex items-center gap-3">
              {(run.status === 'completed' || run.status === 'done') && (
                <span className="text-emerald-600 font-medium">{run.leads_found} leads</span>
              )}
              {duration !== null && <span>{duration}s</span>}
              {run.error_message && (
                <span className="text-rose-500 truncate max-w-xs" title={run.error_message}>
                  {run.error_message}
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ── Config card ───────────────────────────────────────────────────────────────

interface ConfigCardProps {
  config: JobSearchConfig
  onRunNow: (configId: string) => void
  isAnyRunning: boolean
  runningConfigId: string | null
}

function ConfigCard({ config, onRunNow, isAnyRunning, runningConfigId }: ConfigCardProps) {
  const [showHistory, setShowHistory] = useState(false)
  const isThisRunning = runningConfigId === config.id

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm">
      <div className="p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0 space-y-2">
            <div className="flex items-center gap-2">
              <Badge label={config.is_active ? 'active' : 'archived'} asStatus />
            </div>
            <div className="flex flex-wrap gap-1">
              {config.keywords.map(kw => (
                <span key={kw} className="px-2 py-0.5 bg-sky-50 text-sky-700 text-xs rounded font-medium">
                  {kw}
                </span>
              ))}
            </div>
            <p className="text-sm text-slate-600">
              <span className="font-medium text-slate-700">Location:</span> {config.location}
            </p>
            <div className="flex flex-wrap gap-1">
              {config.roles.map(role => (
                <span key={role} className="px-2 py-0.5 bg-slate-100 text-slate-600 text-xs rounded font-medium">
                  {role}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-col items-end gap-2 shrink-0">
            <button
              onClick={() => onRunNow(config.id)}
              disabled={isAnyRunning}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg font-medium transition-colors',
                'bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {isThisRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              {isThisRunning ? 'Running…' : 'Run Now'}
            </button>
            <button
              onClick={() => setShowHistory(v => !v)}
              className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
            >
              {showHistory ? 'Hide history' : 'View history'}
            </button>
          </div>
        </div>
        {showHistory && <RunHistoryPanel configId={config.id} />}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function JobSearch() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>('')
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [runningConfigId, setRunningConfigId] = useState<string | null>(null)

  const { data: campaigns, isLoading: campaignsLoading } = useQuery<Campaign[]>({
    queryKey: ['campaigns'],
    queryFn: () => api.get('/campaigns').then(r => r.data),
  })

  const { data: configs, isLoading: configsLoading } = useQuery<JobSearchConfig[]>({
    queryKey: ['job-search-configs', selectedCampaignId],
    queryFn: () =>
      api.get(`/job-search/configs/${selectedCampaignId}`).then(r => r.data),
    enabled: !!selectedCampaignId,
  })

  const createMutation = useMutation({
    mutationFn: (data: CreateConfigPayload) =>
      api.post('/job-search/configs', { ...data, campaign_id: selectedCampaignId }).then(r => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['job-search-configs', selectedCampaignId] })
      setShowCreateModal(false)
      toast.success('Config created')
    },
    onError: () => toast.error('Failed to create config'),
  })

  const runMutation = useMutation({
    mutationFn: (configId: string) =>
      api.post('/job-search/trigger', { campaign_id: selectedCampaignId, config_id: configId }).then(r => r.data),
    onSuccess: (_, configId) => {
      setRunningConfigId(null)
      toast.success('Run started')
      queryClient.invalidateQueries({ queryKey: ['job-search-runs', configId] })
    },
    onError: () => {
      setRunningConfigId(null)
      toast.error('Failed to start run')
    },
  })

  function handleRunNow(configId: string) {
    setRunningConfigId(configId)
    runMutation.mutate(configId)
  }

  useEffect(() => {
    if (campaigns && campaigns.length > 0 && !selectedCampaignId) {
      setSelectedCampaignId(campaigns[0].id)
    }
  }, [campaigns, selectedCampaignId])

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
          <h1 className="text-xl font-semibold text-slate-900">Job Search</h1>
          <p className="text-sm text-slate-500 mt-0.5">Configure and run job searches per campaign</p>
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

      {/* Campaign selector */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-slate-700 mb-1">Campaign</label>
        <select
          value={selectedCampaignId}
          onChange={e => setSelectedCampaignId(e.target.value)}
          className="border border-slate-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500 bg-white w-72"
        >
          {!selectedCampaignId && <option value="">Select a campaign…</option>}
          {campaigns?.map(c => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      {/* Content */}
      {!selectedCampaignId ? (
        <div className="text-center py-20 text-slate-400 text-sm">
          Select a campaign to view job search configs
        </div>
      ) : configsLoading ? (
        <div className="flex items-center justify-center h-32">
          <Loader2 size={20} className="animate-spin text-slate-400" />
        </div>
      ) : configs && configs.length > 0 ? (
        <div className="space-y-3">
          {configs.map(config => (
            <ConfigCard
              key={config.id}
              config={config}
              onRunNow={handleRunNow}
              isAnyRunning={runMutation.isPending}
              runningConfigId={runningConfigId}
            />
          ))}
        </div>
      ) : (
        <div className="text-center py-20 text-slate-400 text-sm">
          No configs yet.{' '}
          <button
            onClick={() => setShowCreateModal(true)}
            className="text-sky-600 hover:underline"
          >
            Create one
          </button>
        </div>
      )}

      {showCreateModal && selectedCampaignId && (
        <CreateConfigModal
          campaignId={selectedCampaignId}
          onClose={() => setShowCreateModal(false)}
          onSubmit={data => createMutation.mutate(data)}
          isLoading={createMutation.isPending}
        />
      )}
    </div>
  )
}
