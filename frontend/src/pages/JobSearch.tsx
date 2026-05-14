import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { PlusCircle, Play, Loader2, Search, History, Plus, Globe } from 'lucide-react'
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
      toast.success('Search configuration created')
    },
    onError: () => toast.error('Failed to create search configuration'),
  })

  const runMutation = useMutation({
    mutationFn: (configId: string) =>
      api.post('/job-search/trigger', { campaign_id: selectedCampaignId, config_id: configId }).then(r => r.data),
    onSuccess: (_, configId) => {
      setRunningConfigId(null)
      toast.success('Job search run started')
      queryClient.invalidateQueries({ queryKey: ['job-search-runs', configId] })
    },
    onError: () => {
      setRunningConfigId(null)
      toast.error('Failed to start search run')
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

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Lead Gen"
        eyebrow="Job Search"
        title="Job Search"
        description="Monitor specific job boards and roles to trigger automated outreach when companies hire."
        actions={
          <Button
            variant="primary"
            size="md"
            icon={Plus}
            disabled={!selectedCampaignId}
            onClick={() => setShowCreateModal(true)}
          >
            New Search
          </Button>
        }
      />

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
          <div className="space-y-4">{[0,1,2].map(i => <div key={i} className="h-32 skeleton rounded-2xl" />)}</div>
        ) : configs && configs.length > 0 ? (
          <div className="grid gap-4">
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
        ) : selectedCampaignId ? (
          <Card padding="lg">
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-slate-50 dark:bg-slate-900">
                <Search size={24} className="text-slate-300" />
              </div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">No searches configured</h3>
              <p className="mt-1 text-sm text-slate-500">Add a search configuration to start finding leads from job posts.</p>
              <Button 
                variant="primary" 
                size="sm" 
                className="mt-6" 
                icon={Plus}
                onClick={() => setShowCreateModal(true)}
              >
                New Search
              </Button>
            </div>
          </Card>
        ) : (
          <Card padding="lg">
            <div className="flex flex-col items-center justify-center py-12 text-center text-slate-400">
              <Globe size={32} strokeWidth={1.5} />
              <p className="mt-4 text-sm font-medium">Select a campaign to manage job searches</p>
            </div>
          </Card>
        )}
      </div>

      <CreateConfigModal
        open={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        onSubmit={data => createMutation.mutate(data)}
        isLoading={createMutation.isPending}
      />
    </div>
  )
}

function ConfigCard({ config, onRunNow, isAnyRunning, runningConfigId }: { 
  config: JobSearchConfig, 
  onRunNow: (id: string) => void, 
  isAnyRunning: boolean, 
  runningConfigId: string | null 
}) {
  const [showHistory, setShowHistory] = useState(false)
  const isThisRunning = runningConfigId === config.id

  return (
    <Card padding="none">
      <div className="p-6">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0 flex-1 space-y-4">
            <div className="flex items-center gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/30">
                <Search size={16} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold text-slate-900 dark:text-white">Job Search Config</span>
                  <Badge label={config.is_active ? 'active' : 'paused'} asStatus size="xs" dot />
                </div>
                <p className="text-[11px] font-medium text-slate-400">Created {new Date(config.created_at).toLocaleDateString()}</p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-8 lg:grid-cols-3">
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Keywords</p>
                <div className="flex flex-wrap gap-1.5">
                  {config.keywords.map(kw => (
                    <span key={kw} className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {kw}
                    </span>
                  ))}
                </div>
              </div>
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Location</p>
                <p className="text-sm font-semibold text-slate-700 dark:text-slate-300">{config.location}</p>
              </div>
              <div className="space-y-1.5">
                <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Target Roles</p>
                <div className="flex flex-wrap gap-1.5">
                  {config.roles.map(role => (
                    <span key={role} className="rounded-md bg-brand-50 px-2 py-0.5 text-[11px] font-bold text-brand-600 dark:bg-brand-900/20 dark:text-brand-400">
                      {role}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Button
              variant="primary"
              size="sm"
              icon={isThisRunning ? undefined : Play}
              isLoading={isThisRunning}
              disabled={isAnyRunning && !isThisRunning}
              onClick={() => onRunNow(config.id)}
            >
              Run Now
            </Button>
            <Button
              variant="ghost"
              size="sm"
              icon={History}
              onClick={() => setShowHistory(!showHistory)}
            >
              {showHistory ? 'Hide History' : 'History'}
            </Button>
          </div>
        </div>
        
        {showHistory && (
          <div className="mt-6 border-t border-slate-100 pt-6 dark:border-slate-800">
            <RunHistoryPanel configId={config.id} />
          </div>
        )}
      </div>
    </Card>
  )
}

function RunHistoryPanel({ configId }: { configId: string }) {
  const { data: runs, isLoading } = useQuery<JobSearchRun[]>({
    queryKey: ['job-search-runs', configId],
    queryFn: () => api.get('/job-search/runs', { params: { config_id: configId } }).then(r => r.data),
  })

  if (isLoading) return <div className="flex justify-center py-6"><Loader2 size={16} className="animate-spin text-slate-300" /></div>
  if (!runs || runs.length === 0) return <p className="py-4 text-center text-xs text-slate-400">No previous runs found</p>

  return (
    <div className="space-y-2">
      {runs.map(run => (
        <div key={run.id} className="flex items-center justify-between rounded-lg bg-slate-50/50 px-4 py-2 dark:bg-slate-900/50">
          <div className="flex items-center gap-3">
            <Badge label={run.status} variant={run.status === 'completed' || run.status === 'done' ? 'success' : run.status === 'failed' ? 'danger' : 'info'} size="xs" />
            <span className="text-[11px] font-medium text-slate-500">{new Date(run.started_at).toLocaleString()}</span>
          </div>
          <div className="flex items-center gap-4">
            {(run.status === 'completed' || run.status === 'done') && (
              <span className="text-[11px] font-bold text-emerald-600">+{run.leads_found} leads</span>
            )}
            {run.error_message && <span className="max-w-[200px] truncate text-[11px] text-rose-500" title={run.error_message}>{run.error_message}</span>}
          </div>
        </div>
      ))}
    </div>
  )
}

function CreateConfigModal({ open, onClose, onSubmit, isLoading }: { 
  open: boolean, 
  onClose: () => void, 
  onSubmit: (data: CreateConfigPayload) => void, 
  isLoading: boolean 
}) {
  const [keywords, setKeywords] = useState('')
  const [location, setLocation] = useState('')
  const [roles, setRoles] = useState('')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    onSubmit({
      campaign_id: '', // Handled by parent
      keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
      location: location.trim(),
      roles: roles.split(',').map(r => r.trim()).filter(Boolean),
    })
  }

  const inputCls = "w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 outline-none transition focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:border-slate-800 dark:bg-slate-900 dark:text-white dark:focus:ring-brand-900/20"

  return (
    <Modal title="New Job Search Config" open={open} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-4">
          <div>
            <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Search Keywords</label>
            <input
              type="text"
              required
              value={keywords}
              onChange={e => setKeywords(e.target.value)}
              className={inputCls}
              placeholder="e.g. software engineer, react developer"
            />
            <p className="mt-1.5 text-[10px] font-medium text-slate-400">Comma-separated keywords for job board queries</p>
          </div>
          <div>
            <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Geographic Location</label>
            <input
              type="text"
              required
              value={location}
              onChange={e => setLocation(e.target.value)}
              className={inputCls}
              placeholder="e.g. San Francisco, CA or Remote"
            />
          </div>
          <div>
            <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Target Role Titles</label>
            <input
              type="text"
              required
              value={roles}
              onChange={e => setRoles(e.target.value)}
              className={inputCls}
              placeholder="e.g. Frontend Engineer, Full Stack"
            />
            <p className="mt-1.5 text-[10px] font-medium text-slate-400">Comma-separated exact role titles to match</p>
          </div>
        </div>
        
        <div className="flex justify-end gap-3 pt-4 border-t border-slate-100 dark:border-slate-800">
          <Button variant="secondary" size="md" onClick={onClose} disabled={isLoading}>Cancel</Button>
          <Button type="submit" variant="primary" size="md" isLoading={isLoading}>Create Configuration</Button>
        </div>
      </form>
    </Modal>
  )
}
