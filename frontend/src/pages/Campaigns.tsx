import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Plus, Upload } from 'lucide-react'
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
  const sequencesQuery = useQuery({
    queryKey: ['sequence-steps', id],
    enabled: !!id,
    queryFn: async () => {
      const { data } = await api.get(`/sequences?campaign_id=${id}`)
      return data
    },
    retry: false,
  })

  const [createOpen, setCreateOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
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
              <h2 className="text-lg font-semibold text-slate-900">Sequence steps</h2>
              <p className="mb-4 text-sm text-slate-500">This backend route is still a stub, so the frontend shows the current state honestly.</p>
              {sequencesQuery.isError ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-700">
                  Sequence endpoints are not implemented yet on the backend.
                </div>
              ) : (
                <pre className="overflow-auto rounded-2xl border border-slate-200 bg-slate-50 p-4 text-xs text-slate-600">
                  {JSON.stringify(sequencesQuery.data, null, 2)}
                </pre>
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
    </div>
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
