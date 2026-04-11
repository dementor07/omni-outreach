import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ChevronUp, ChevronDown, ListOrdered, Linkedin, Mail, Phone, Plus, Trash2, Upload } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/time'
import {
  CampaignPayload,
  useCampaignStats,
  useCreateCampaign,
  useDeleteCampaign,
  useGetCampaign,
  useListCampaigns,
  useUpdateCampaign,
} from '../hooks/useCampaigns'
import { useImportLeads, useListLeads } from '../hooks/useLeads'
import { useQueueList } from '../hooks/useQueue'
import {
  useListSteps,
  useCreateStep,
  useUpdateStep,
  useDeleteStep,
  useGetTemplate,
  useUpsertTemplate,
  type SequenceStep,
  type ChannelType,
} from '../hooks/useSequenceSteps'

type CampaignTab = 'leads' | 'queue' | 'sequence'

const defaultCampaignForm: CampaignPayload = {
  name: '',
  daily_lead_cap: 50,
  invite_daily_cap: 20,
  simulation_mode: false,
  timezone: 'Asia/Kolkata',
  active_hours_start: 9,
  active_hours_end: 18,
  screening_prompt: '',
}

function parseJsonImport(raw: string) {
  const parsed = JSON.parse(raw)
  if (!Array.isArray(parsed)) throw new Error('Expected a JSON array of lead objects')
  return parsed
}

export default function Campaigns() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = (searchParams.get('tab') as CampaignTab | null) || 'leads'
  const toast = useToast()

  const campaignsQuery = useListCampaigns()
  const campaignQuery = useGetCampaign(id)
  const statsQuery = useCampaignStats(id)
  const createCampaign = useCreateCampaign()
  const updateCampaign = useUpdateCampaign()
  const deleteCampaign = useDeleteCampaign()
  const importLeads = useImportLeads()
  const leadsQuery = useListLeads(id, 1, 50)
  const queueQuery = useQueueList({ campaignId: id, limit: 100 })
  const stepsQuery = useListSteps(id)
  const createStep = useCreateStep()
  const updateStep = useUpdateStep()
  const deleteStep = useDeleteStep()

  const [createOpen, setCreateOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [stepModalOpen, setStepModalOpen] = useState(false)
  const [templateModalStep, setTemplateModalStep] = useState<SequenceStep | null>(null)
  const [form, setForm] = useState<CampaignPayload>(defaultCampaignForm)
  const [importPayload, setImportPayload] = useState('')
  const [importError, setImportError] = useState('')

  useEffect(() => {
    if (!campaignQuery.data) return
    setForm({
      name: campaignQuery.data.name,
      daily_lead_cap: campaignQuery.data.daily_lead_cap,
      invite_daily_cap: campaignQuery.data.invite_daily_cap,
      simulation_mode: campaignQuery.data.simulation_mode,
      timezone: campaignQuery.data.timezone,
      active_hours_start: campaignQuery.data.active_hours_start,
      active_hours_end: campaignQuery.data.active_hours_end,
      screening_prompt: campaignQuery.data.screening_prompt || '',
      status: campaignQuery.data.status,
    })
  }, [campaignQuery.data])

  const campaignRows = campaignsQuery.data || []
  const detailLeads = leadsQuery.data?.leads || []
  const detailQueue = queueQuery.data || []
  const stats = statsQuery.data

  const campaignColumns = useMemo(
    () => [
      {
        key: 'name',
        header: 'Campaign',
        render: (row: typeof campaignRows[number]) => (
          <div>
            <p className="font-medium text-slate-900">{row.name}</p>
            <p className="text-xs uppercase tracking-[0.16em] text-slate-400">{row.timezone}</p>
          </div>
        ),
      },
      {
        key: 'status',
        header: 'Status',
        render: (row: typeof campaignRows[number]) => <Badge label={row.status || 'active'} asStatus />,
      },
      {
        key: 'daily_lead_cap',
        header: 'Daily Leads',
        className: 'text-right',
        render: (row: typeof campaignRows[number]) => <span className="tabular-nums">{row.daily_lead_cap}</span>,
      },
      {
        key: 'invite_daily_cap',
        header: 'Invite Cap',
        className: 'text-right',
        render: (row: typeof campaignRows[number]) => <span className="tabular-nums">{row.invite_daily_cap}</span>,
      },
      {
        key: 'simulation_mode',
        header: 'Mode',
        render: (row: typeof campaignRows[number]) => (
          <Badge label={row.simulation_mode ? 'simulation' : 'live'} variant={row.simulation_mode ? 'warning' : 'success'} />
        ),
      },
      {
        key: 'created_at',
        header: 'Created',
        render: (row: typeof campaignRows[number]) => formatDate(row.created_at),
      },
    ],
    [campaignRows],
  )

  async function handleCreateCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    try {
      await createCampaign.mutateAsync(form)
      setCreateOpen(false)
      setForm(defaultCampaignForm)
      toast.success('Campaign created.')
    } catch {
      toast.error('Failed to create campaign.')
    }
  }

  async function handleSaveCampaign(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!id) return
    try {
      await updateCampaign.mutateAsync({ id, payload: form })
      toast.success('Campaign saved.')
    } catch {
      toast.error('Failed to save campaign.')
    }
  }

  async function handleArchiveCampaign() {
    if (!id) return
    try {
      await deleteCampaign.mutateAsync(id)
      toast.success('Campaign archived.')
      navigate('/campaigns')
    } catch {
      toast.error('Failed to archive campaign.')
    }
  }

  async function handleImportLeads(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!id) return
    try {
      setImportError('')
      const parsed = parseJsonImport(importPayload)
      const result = await importLeads.mutateAsync({ campaignId: id, leads: parsed })
      setImportOpen(false)
      setImportPayload('')
      toast.success(`Imported ${result.imported} leads${result.skipped ? `, ${result.skipped} skipped` : ''}.`)
    } catch (error) {
      setImportError(error instanceof Error ? error.message : 'Import failed')
    }
  }

  if (!id) {
    return (
      <div className="space-y-6">
        <section className="flex items-start justify-between rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Campaigns</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Configure the outreach engine campaign by campaign</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Build campaign constraints, choose operating hours, and drop into deeper views when you need leads or queue detail.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-sky-600"
          >
            <Plus size={16} />
            New Campaign
          </button>
        </section>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          {campaignRows.length === 0 && !campaignsQuery.isLoading ? (
            <EmptyState icon={Plus} title="No campaigns created yet" description="Create your first campaign to start feeding leads into the system." />
          ) : (
            <DataTable
              columns={campaignColumns}
              rows={campaignRows}
              loading={campaignsQuery.isLoading}
              onRowClick={(row) => navigate(`/campaigns/${row.id}?tab=leads`)}
            />
          )}
        </div>

        <Modal title="New campaign" open={createOpen} onClose={() => setCreateOpen(false)} width="lg">
          <CampaignForm
            form={form}
            onChange={setForm}
            onSubmit={handleCreateCampaign}
            busy={createCampaign.isPending}
            submitLabel="Create campaign"
          />
        </Modal>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <Link to="/campaigns" className="text-sm font-medium text-sky-500 hover:text-sky-600">← Back to campaigns</Link>
            <div className="mt-3 flex items-center gap-3">
              <h1 className="text-3xl font-semibold tracking-tight text-slate-900">
                {campaignQuery.data?.name || 'Campaign detail'}
              </h1>
              {campaignQuery.data && (
                <button
                  type="button"
                  onClick={async () => {
                    const current = campaignQuery.data.status
                    const next = current === 'paused' ? 'active' : 'paused'
                    try {
                      await updateCampaign.mutateAsync({ id: id!, payload: { status: next } })
                      toast.success(`Campaign ${next === 'active' ? 'resumed' : 'paused'}.`)
                    } catch {
                      toast.error('Failed to update campaign status.')
                    }
                  }}
                  className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                    campaignQuery.data.status === 'paused'
                      ? 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                      : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                  }`}
                >
                  {campaignQuery.data.status === 'paused' ? 'Resume' : 'Pause'}
                </button>
              )}
            </div>
            <div className="mt-3 flex flex-wrap gap-3 text-sm text-slate-500">
              <span className="rounded-full bg-slate-100 px-3 py-1">{campaignQuery.data?.timezone || 'Asia/Kolkata'}</span>
              <span className="rounded-full bg-slate-100 px-3 py-1">
                Active hours {campaignQuery.data?.active_hours_start ?? 9}:00 to {campaignQuery.data?.active_hours_end ?? 18}:00
              </span>
            </div>
          </div>
          {stats && (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
              <MiniStat label="Total" value={stats.total} />
              <MiniStat label="Active" value={stats.active} />
              <MiniStat label="Invited" value={stats.invited} />
              <MiniStat label="Accepted" value={stats.accepted} />
              <MiniStat label="Stopped" value={stats.stopped} />
            </div>
          )}
        </div>
      </section>

      <div className="flex flex-wrap gap-2">
        {(['leads', 'queue', 'sequence'] as CampaignTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setSearchParams({ tab })}
            className={`rounded-full px-4 py-2 text-sm font-medium transition ${
              activeTab === tab ? 'bg-sky-500 text-white' : 'bg-white text-slate-500 hover:bg-slate-100'
            }`}
          >
            {tab === 'sequence' ? 'Sequence steps' : tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[0.8fr_1.2fr]">
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold text-slate-900">Campaign settings</h2>
          <p className="mt-1 text-sm text-slate-500">Tune pacing, simulation mode, and screening from the same control surface.</p>
          <div className="mt-5">
            <CampaignForm
              form={form}
              onChange={setForm}
              onSubmit={handleSaveCampaign}
              busy={updateCampaign.isPending}
              submitLabel="Save campaign"
              compact
            />
          </div>
          <button
            type="button"
            onClick={handleArchiveCampaign}
            className="mt-4 text-sm font-medium text-rose-600 hover:text-rose-700"
          >
            Archive campaign
          </button>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          {activeTab === 'leads' && (
            <>
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Campaign leads</h2>
                  <p className="text-sm text-slate-500">Imported and enriched leads for this campaign.</p>
                </div>
                <button
                  type="button"
                  onClick={() => setImportOpen(true)}
                  className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
                >
                  <Upload size={16} />
                  Import leads
                </button>
              </div>
              <DataTable
                columns={[
                  {
                    key: 'name',
                    header: 'Lead',
                    render: (row) => (
                      <div>
                        <p className="font-medium text-slate-900">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || 'Unknown'}</p>
                        <p className="text-xs text-slate-400">{row.company || '—'}</p>
                      </div>
                    ),
                  },
                  { key: 'headline', header: 'Headline', render: (row) => <span className="line-clamp-2">{row.headline || '—'}</span> },
                  { key: 'status', header: 'Status', render: (row) => <Badge label={row.status || 'active'} asStatus /> },
                  { key: 'invited_at', header: 'Invited', render: (row) => formatDate(row.invited_at) },
                  { key: 'accepted_at', header: 'Accepted', render: (row) => formatDate(row.accepted_at) },
                ]}
                rows={detailLeads}
                loading={leadsQuery.isLoading}
                emptyMessage="No leads imported for this campaign yet."
              />
            </>
          )}

          {activeTab === 'queue' && (
            <>
              <h2 className="text-lg font-semibold text-slate-900">Queue for this campaign</h2>
              <p className="mb-4 text-sm text-slate-500">Tasks scheduled for the selected campaign.</p>
              <DataTable
                columns={[
                  {
                    key: 'lead',
                    header: 'Lead',
                    render: (row) => `${row.first_name || ''} ${row.last_name || ''}`.trim() || row.linkedin_url || 'Unknown',
                  },
                  { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                  { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
                  { key: 'scheduled_at', header: 'Scheduled', render: (row) => formatDate(row.scheduled_at) },
                  { key: 'retry_count', header: 'Retries', className: 'text-right', render: (row) => row.retry_count || 0 },
                ]}
                rows={detailQueue}
                loading={queueQuery.isLoading}
                emptyMessage="No queue tasks yet for this campaign."
              />
            </>
          )}

          {activeTab === 'sequence' && (
            <>
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">Sequence steps</h2>
                  <p className="text-sm text-slate-500">Define the outreach order, channel, and delay for each step.</p>
                </div>
                <button
                  type="button"
                  onClick={() => setStepModalOpen(true)}
                  className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-sky-600"
                >
                  <Plus size={15} />
                  Add step
                </button>
              </div>

              {stepsQuery.isLoading && (
                <div className="space-y-2">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-14 animate-pulse rounded-2xl bg-slate-100" />
                  ))}
                </div>
              )}

              {!stepsQuery.isLoading && (stepsQuery.data?.length ?? 0) === 0 && (
                <EmptyState
                  icon={ListOrdered}
                  title="No sequence steps yet"
                  description="Add your first step to define how outreach progresses after acceptance."
                />
              )}

              {!stepsQuery.isLoading && (stepsQuery.data?.length ?? 0) > 0 && (
                <div className="space-y-2">
                  {(stepsQuery.data ?? []).map((step, idx) => {
                    const steps = stepsQuery.data ?? []
                    return (
                      <SequenceStepRow
                        key={step.id}
                        step={step}
                        isFirst={idx === 0}
                        isLast={idx === steps.length - 1}
                        onMove={async (dir) => {
                          const swapWith = steps[dir === 'up' ? idx - 1 : idx + 1]
                          if (!swapWith) return
                          try {
                            // Use a temporary order to avoid unique constraint collision
                            const tmp = -1
                            await updateStep.mutateAsync({ id: step.id, campaignId: step.campaign_id, payload: { step_order: tmp } })
                            await updateStep.mutateAsync({ id: swapWith.id, campaignId: swapWith.campaign_id, payload: { step_order: step.step_order } })
                            await updateStep.mutateAsync({ id: step.id, campaignId: step.campaign_id, payload: { step_order: swapWith.step_order } })
                          } catch {
                            toast.error('Failed to reorder steps.')
                          }
                        }}
                        onDelete={async () => {
                          try {
                            await deleteStep.mutateAsync({ id: step.id, campaignId: step.campaign_id })
                            toast.success('Step deleted.')
                          } catch {
                            toast.error('Failed to delete step.')
                          }
                        }}
                        onEditTemplate={() => setTemplateModalStep(step)}
                      />
                    )
                  })}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <Modal title="Import leads" open={importOpen} onClose={() => setImportOpen(false)} width="lg">
        <form className="space-y-4" onSubmit={handleImportLeads}>
          <p className="text-sm text-slate-500">
            Paste a JSON array of lead objects. Each object should at least include `linkedin_url`.
          </p>
          <textarea
            value={importPayload}
            onChange={(event) => setImportPayload(event.target.value)}
            className="min-h-[260px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-800 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
            placeholder='[{"linkedin_url":"https://linkedin.com/in/example","first_name":"Ava"}]'
          />
          {importError && <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">{importError}</div>}
          <div className="flex justify-end gap-3">
            <button type="button" onClick={() => setImportOpen(false)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600">
              Cancel
            </button>
            <button type="submit" className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white" disabled={importLeads.isPending}>
              {importLeads.isPending ? 'Importing...' : 'Import leads'}
            </button>
          </div>
        </form>
      </Modal>

      <AddStepModal
        open={stepModalOpen}
        campaignId={id!}
        existingOrders={(stepsQuery.data ?? []).map((s) => s.step_order)}
        onClose={() => setStepModalOpen(false)}
        onCreate={async (payload) => {
          try {
            await createStep.mutateAsync(payload)
            toast.success('Step added.')
          } catch {
            toast.error('Failed to add step.')
          }
        }}
      />

      <TemplateModal
        step={templateModalStep}
        onClose={() => setTemplateModalStep(null)}
      />
    </div>
  )
}

function SequenceStepRow({
  step,
  isFirst,
  isLast,
  onMove,
  onDelete,
  onEditTemplate,
}: {
  step: SequenceStep
  isFirst: boolean
  isLast: boolean
  onMove: (dir: 'up' | 'down') => Promise<void>
  onDelete: () => void
  onEditTemplate: () => void
}) {
  const channelIcon: Record<ChannelType, React.ReactNode> = {
    linkedin_invite: <Linkedin size={14} className="text-sky-500" />,
    linkedin_dm: <Linkedin size={14} className="text-sky-500" />,
    email: <Mail size={14} className="text-slate-500" />,
    voice: <Phone size={14} className="text-emerald-500" />,
  }

  const hasTemplate = step.channel !== 'linkedin_invite'

  return (
    <div className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="flex flex-col gap-0.5">
        <button type="button" disabled={isFirst} onClick={() => onMove('up')} className="text-slate-300 hover:text-slate-500 disabled:opacity-30" title="Move up">
          <ChevronUp size={14} />
        </button>
        <button type="button" disabled={isLast} onClick={() => onMove('down')} className="text-slate-300 hover:text-slate-500 disabled:opacity-30" title="Move down">
          <ChevronDown size={14} />
        </button>
      </div>

      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-slate-200 bg-white text-xs font-semibold text-slate-500">
        {step.step_order}
      </div>

      <div className="flex min-w-[8rem] items-center gap-1.5">
        {channelIcon[step.channel]}
        <Badge label={step.channel} asChannel />
      </div>

      <div className="flex-1 text-sm text-slate-500">
        {step.delay_days === 0 ? 'Immediately' : `+${step.delay_days} day${step.delay_days !== 1 ? 's' : ''}`}
        {step.voice_agent_name && (
          <span className="ml-2 text-xs text-slate-400">· {step.voice_agent_name}</span>
        )}
        {step.email_account_email && (
          <span className="ml-2 text-xs text-slate-400">· {step.email_account_email}</span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {hasTemplate && (
          <button
            type="button"
            onClick={onEditTemplate}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 transition-colors hover:bg-white"
          >
            Edit template
          </button>
        )}
        <button
          type="button"
          onClick={onDelete}
          className="rounded-lg border border-rose-200 p-1.5 text-rose-400 transition-colors hover:bg-rose-50"
          title="Delete step"
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  )
}

function AddStepModal({
  open,
  campaignId,
  existingOrders,
  onClose,
  onCreate,
}: {
  open: boolean
  campaignId: string
  existingOrders: number[]
  onClose: () => void
  onCreate: (payload: {
    campaign_id: string
    step_order: number
    channel: ChannelType
    delay_days: number
    voice_agent_id?: string | null
    email_account_id?: string | null
  }) => Promise<void>
}) {
  const nextOrder = existingOrders.length === 0 ? 0 : Math.max(...existingOrders) + 1

  const [channel, setChannel] = useState<ChannelType>('linkedin_invite')
  const [stepOrder, setStepOrder] = useState(nextOrder)
  const [delayDays, setDelayDays] = useState(0)
  const [voiceAgentId, setVoiceAgentId] = useState('')
  const [emailAccountId, setEmailAccountId] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (open) {
      const next = existingOrders.length === 0 ? 0 : Math.max(...existingOrders) + 1
      setChannel('linkedin_invite')
      setStepOrder(next)
      setDelayDays(0)
      setVoiceAgentId('')
      setEmailAccountId('')
    }
  }, [open])

  const voiceAgentsQuery = useQuery({
    queryKey: ['settings', 'voice'],
    queryFn: async () => (await api.get<{ id: string; name: string; retell_agent_id: string }[]>('/accounts/voice')).data,
    enabled: open && channel === 'voice',
  })

  const emailAccountsQuery = useQuery({
    queryKey: ['settings', 'email'],
    queryFn: async () => (await api.get<{ id: string; from_name: string; from_email: string }[]>('/accounts/email')).data,
    enabled: open && channel === 'email',
  })

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setBusy(true)
    try {
      await onCreate({
        campaign_id: campaignId,
        step_order: stepOrder,
        channel,
        delay_days: delayDays,
        voice_agent_id: channel === 'voice' ? voiceAgentId || null : null,
        email_account_id: channel === 'email' ? emailAccountId || null : null,
      })
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Add sequence step" open={open} onClose={onClose}>
      <form className="space-y-4" onSubmit={handleSubmit}>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Step order</span>
            <input
              type="number"
              min={0}
              value={stepOrder}
              onChange={(e) => setStepOrder(Number(e.target.value))}
              className={inputClassName}
              required
            />
          </label>
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Delay (days)</span>
            <input
              type="number"
              min={0}
              value={delayDays}
              onChange={(e) => setDelayDays(Number(e.target.value))}
              className={inputClassName}
              required
            />
          </label>
        </div>

        <label className="block">
          <span className="mb-1.5 block text-sm font-medium text-slate-700">Channel</span>
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as ChannelType)}
            className={inputClassName}
          >
            <option value="linkedin_invite">LinkedIn Invite</option>
            <option value="linkedin_dm">LinkedIn DM</option>
            <option value="email">Email</option>
            <option value="voice">Voice call</option>
          </select>
        </label>

        {channel === 'voice' && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Voice agent</span>
            <select
              value={voiceAgentId}
              onChange={(e) => setVoiceAgentId(e.target.value)}
              className={inputClassName}
              required
            >
              <option value="">Select an agent…</option>
              {(voiceAgentsQuery.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
        )}

        {channel === 'email' && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Email account</span>
            <select
              value={emailAccountId}
              onChange={(e) => setEmailAccountId(e.target.value)}
              className={inputClassName}
              required
            >
              <option value="">Select an account…</option>
              {(emailAccountsQuery.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.from_name} ({a.from_email})</option>
              ))}
            </select>
          </label>
        )}

        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-600 disabled:opacity-60"
          >
            {busy ? 'Adding…' : 'Add step'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function TemplateModal({ step, onClose }: { step: SequenceStep | null; onClose: () => void }) {
  const open = !!step
  const toast = useToast()
  const templateQuery = useGetTemplate(step?.id)
  const upsertTemplate = useUpsertTemplate()

  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')

  useEffect(() => {
    if (templateQuery.data) {
      setSubject(templateQuery.data.subject ?? '')
      setBody(templateQuery.data.body ?? '')
    } else if (!templateQuery.isLoading && open) {
      setSubject('')
      setBody('')
    }
  }, [templateQuery.data, templateQuery.isLoading, open])

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!step) return
    try {
      await upsertTemplate.mutateAsync({ step_id: step.id, subject: subject || null, body })
      toast.success('Template saved.')
      onClose()
    } catch {
      toast.error('Failed to save template.')
    }
  }

  const hasSubject = step?.channel === 'email'

  return (
    <Modal title="Edit step template" open={open} onClose={onClose} width="lg">
      <div className="mb-3 flex items-center gap-2">
        {step && <Badge label={step.channel} asChannel />}
        <span className="text-xs text-slate-400">
          Variables:{' '}
          <code className="rounded bg-slate-100 px-1 font-mono">{'{{first_name}}'}</code>{' '}
          <code className="rounded bg-slate-100 px-1 font-mono">{'{{company}}'}</code>{' '}
          <code className="rounded bg-slate-100 px-1 font-mono">{'{{last_name}}'}</code>
        </span>
      </div>
      {templateQuery.isLoading ? (
        <div className="h-32 animate-pulse rounded-2xl bg-slate-100" />
      ) : (
        <form className="space-y-4" onSubmit={handleSubmit}>
          {hasSubject && (
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">Subject</span>
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                className={inputClassName}
                placeholder="e.g. Quick question, {{first_name}}"
              />
            </label>
          )}
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Message body</span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className={`${inputClassName} min-h-[200px]`}
              placeholder="Hi {{first_name}}, saw that {{company}} is hiring…"
              required
            />
          </label>
          <div className="flex justify-end gap-3">
            <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600">
              Cancel
            </button>
            <button
              type="submit"
              disabled={upsertTemplate.isPending}
              className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-sky-600 disabled:opacity-60"
            >
              {upsertTemplate.isPending ? 'Saving…' : 'Save template'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}

function CampaignForm({
  form,
  onChange,
  onSubmit,
  busy,
  submitLabel,
  compact = false,
}: {
  form: CampaignPayload
  onChange: (payload: CampaignPayload) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void | Promise<void>
  busy: boolean
  submitLabel: string
  compact?: boolean
}) {
  function update<K extends keyof CampaignPayload>(key: K, value: CampaignPayload[K]) {
    onChange({ ...form, [key]: value })
  }

  return (
    <form className={compact ? 'space-y-4' : 'space-y-5'} onSubmit={onSubmit}>
      <div className={compact ? 'grid gap-4' : 'grid gap-4 md:grid-cols-2'}>
        <Field label="Campaign name">
          <input value={form.name} onChange={(event) => update('name', event.target.value)} className={inputClassName} required />
        </Field>
        <Field label="Timezone">
          <input value={form.timezone} onChange={(event) => update('timezone', event.target.value)} className={inputClassName} required />
        </Field>
        <Field label="Daily lead cap">
          <input type="number" value={form.daily_lead_cap} onChange={(event) => update('daily_lead_cap', Number(event.target.value))} className={inputClassName} required />
        </Field>
        <Field label="Invite daily cap">
          <input type="number" value={form.invite_daily_cap} onChange={(event) => update('invite_daily_cap', Number(event.target.value))} className={inputClassName} required />
        </Field>
        <Field label="Active hours start">
          <input type="number" min={0} max={23} value={form.active_hours_start} onChange={(event) => update('active_hours_start', Number(event.target.value))} className={inputClassName} required />
        </Field>
        <Field label="Active hours end">
          <input type="number" min={0} max={23} value={form.active_hours_end} onChange={(event) => update('active_hours_end', Number(event.target.value))} className={inputClassName} required />
        </Field>
      </div>

      <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        <input type="checkbox" checked={form.simulation_mode} onChange={(event) => update('simulation_mode', event.target.checked)} />
        Run this campaign in simulation mode
      </label>

      <Field label="Screening prompt">
        <textarea value={form.screening_prompt || ''} onChange={(event) => update('screening_prompt', event.target.value)} className={`${inputClassName} min-h-[120px]`} />
      </Field>

      <div className="flex justify-end">
        <button type="submit" className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white" disabled={busy}>
          {busy ? 'Saving...' : submitLabel}
        </button>
      </div>
    </form>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-center">
      <div className="text-xs uppercase tracking-[0.14em] text-slate-400">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-900">{value}</div>
    </div>
  )
}

const inputClassName =
  'w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100'
