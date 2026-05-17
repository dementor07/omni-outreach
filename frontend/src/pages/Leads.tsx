import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users, Activity, MessageSquare, X as XIcon, Plus, ArrowUpRight, MoreHorizontal, ChevronRight, Megaphone, Upload, UserPlus } from 'lucide-react'
import { useToast } from '../components/Toast'
import { clsx } from 'clsx'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import DataTable from '../components/DataTable'
import Modal from '../components/Modal'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'
import Avatar from '../components/Avatar'
import ChannelIcon from '../components/ChannelIcon'
import { fullName, timeAgo } from '../lib/format'

interface Lead {
  id: string; first_name?: string; last_name?: string; headline?: string; company?: string
  linkedin_url?: string; email?: string; phone?: string; status: string
  invited_at?: string; accepted_at?: string; replied_at?: string; created_at: string
}
interface Campaign { id: string; name: string }

export default function Leads() {
  const toast = useToast()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const [campaignId, setCampaignId] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addForm, setAddForm] = useState({
    first_name: '', last_name: '', linkedin_url: '', email: '', phone: '', company: '', headline: '',
  })

  async function handleAddManual() {
    if (!campaignId) { toast.error('Pick a campaign first'); return }
    const has = addForm.linkedin_url || addForm.email || addForm.phone
    if (!has) { toast.error('Need at least one of LinkedIn URL, email, or phone'); return }
    setAdding(true)
    try {
      await api.post('/leads', addForm, { params: { campaign_id: campaignId } })
      toast.success('Lead added')
      setAddOpen(false)
      setAddForm({ first_name: '', last_name: '', linkedin_url: '', email: '', phone: '', company: '', headline: '' })
      leadsQ.refetch()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to add lead'
      toast.error(msg)
    } finally {
      setAdding(false)
    }
  }

  async function handleExport() {
    if (!campaignId) { toast.error('Pick a campaign first'); return }
    setExporting(true)
    try {
      const res = await api.get(`/leads/export`, { params: { campaign_id: campaignId }, responseType: 'blob' })
      const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `leads_${campaignId}.csv`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Export started')
    } catch {
      toast.error('Export failed')
    } finally {
      setExporting(false)
    }
  }

  async function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    if (!campaignId) { toast.error('Pick a campaign first'); return }
    setImporting(true)
    try {
      const form = new FormData()
      form.append('file', file)
      await api.post('/leads/csv-upload', form, {
        params: { campaign_id: campaignId },
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      toast.success('Leads imported')
      leadsQ.refetch()
    } catch {
      toast.error('Import failed')
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  useEffect(() => {
    if (!campaignId && campaignsQ.data?.length) setCampaignId(campaignsQ.data[0].id)
  }, [campaignsQ.data, campaignId])

  const params = new URLSearchParams()
  if (campaignId) params.set('campaign_id', campaignId)
  if (search) params.set('search', search)
  if (status) params.set('status', status)
  params.set('page_size', '50')

  const leadsQ = useQuery<{ leads: Lead[]; total: number }>({
    queryKey: ['leads', campaignId, search, status],
    queryFn: () => api.get(`/leads?${params.toString()}`).then(r => r.data),
    enabled: !!campaignId,
  })

  const leads = leadsQ.data?.leads || []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Leads"
        eyebrow="Pipeline"
        title="Leads"
        description="Every prospect across the selected campaign, with current pipeline state."
        actions={
          <>
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv,text/csv"
              aria-label="Upload leads CSV"
              title="Upload leads CSV"
              className="hidden"
              onChange={handleImportFile}
            />
            <Button variant="secondary" size="md" icon={ArrowUpRight} onClick={handleExport} disabled={exporting || !campaignId}>
              {exporting ? 'Exporting…' : 'Export CSV'}
            </Button>
            <Button variant="secondary" size="md" icon={Upload} onClick={() => fileInputRef.current?.click()} disabled={importing || !campaignId}>
              {importing ? 'Importing…' : 'Import CSV'}
            </Button>
            <Button variant="primary" size="md" icon={UserPlus} onClick={() => setAddOpen(true)} disabled={!campaignId}>
              Add lead
            </Button>
          </>
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total" value={leadsQ.isLoading ? '—' : (leadsQ.data?.total ?? 0)} accent="brand" icon={Users} />
        <StatCard label="Active" value={leadsQ.isLoading ? '—' : leads.filter(l => l.status === 'active').length} accent="emerald" icon={Activity} />
        <StatCard label="Replied" value={leadsQ.isLoading ? '—' : leads.filter(l => l.replied_at).length} accent="brand" icon={MessageSquare} />
        <StatCard label="Stopped" value={leadsQ.isLoading ? '—' : leads.filter(l => l.status === 'stopped').length} accent="rose" icon={XIcon} />
      </section>

      <FilterBar>
        <SearchInput placeholder="Search by name, company, headline…" value={search} onChange={setSearch} />
        <Select value={campaignId} onChange={setCampaignId}>
          {(campaignsQ.data || []).length === 0 && <option value="">No campaigns</option>}
          {(campaignsQ.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <Select value={status} onChange={setStatus}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="replied">Replied</option>
          <option value="stopped">Stopped</option>
        </Select>
      </FilterBar>

      <Card padding="none">
        {!campaignId ? (
          <EmptyState icon={Megaphone} title="Choose a campaign" description="Select a campaign to view its leads." />
        ) : leadsQ.isLoading ? (
          <div className="space-y-1 p-4">{[0,1,2,3,4].map(i => <div key={i} className="h-12 skeleton" />)}</div>
        ) : leads.length === 0 ? (
          <EmptyState
            icon={Users}
            title="No leads in this campaign"
            description="Import a CSV, connect a lead source, or add prospects manually."
            action={<Button variant="primary" size="sm" icon={UserPlus} onClick={() => setAddOpen(true)}>Add lead</Button>}
          />
        ) : (
          <DataTable
            columns={[
              { key: 'name', header: 'Lead', render: (row: Lead) => (
                <div className="flex items-center gap-2.5">
                  <Avatar name={fullName(row)} size={32} />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-900 dark:text-white">{fullName(row)}</div>
                    {row.headline && <div className="truncate text-[12px] text-slate-500">{row.headline}</div>}
                  </div>
                </div>
              )},
              { key: 'company', header: 'Company', render: (row: Lead) => <span className="text-slate-700 dark:text-slate-300">{row.company || <span className="text-slate-300">—</span>}</span> },
              { key: 'channels', header: 'Channels', render: (row: Lead) => (
                <div className="flex items-center gap-1">
                  {row.linkedin_url && <ChannelIcon channel="linkedin" size="sm" />}
                  {row.email && <ChannelIcon channel="email" size="sm" />}
                  {row.phone && <ChannelIcon channel="sms" size="sm" />}
                </div>
              )},
              { key: 'status', header: 'Status', render: (row: Lead) => <Badge label={row.status || 'active'} asStatus dot /> },
              { key: 'progress', header: 'Progress', render: (row: Lead) => (
                <div className="flex items-center gap-1.5">
                  <Pip on={!!row.invited_at} />
                  <ChevronRight size={10} className="text-slate-300" />
                  <Pip on={!!row.accepted_at} />
                  <ChevronRight size={10} className="text-slate-300" />
                  <Pip on={!!row.replied_at} />
                </div>
              )},
              { key: 'created_at', header: 'Added', render: (row: Lead) => <span className="text-xs tabular-nums text-slate-500">{timeAgo(row.created_at)}</span> },
              { key: 'actions', header: '', align: 'right' as const, render: () => <Button variant="ghost" size="sm" icon={MoreHorizontal} /> },
            ]}
            rows={leads}
          />
        )}
      </Card>

      <Modal title="Add lead manually" open={addOpen} onClose={() => !adding && setAddOpen(false)} width="md">
        <div className="space-y-3">
          <p className="text-[12px] text-slate-500 dark:text-slate-400">
            Provide at least one of: LinkedIn URL, email, or phone. Name fields personalize the sequence.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name">
              <input type="text" value={addForm.first_name} onChange={(e) => setAddForm({ ...addForm, first_name: e.target.value })} className={inputCls} placeholder="Jane" />
            </Field>
            <Field label="Last name">
              <input type="text" value={addForm.last_name} onChange={(e) => setAddForm({ ...addForm, last_name: e.target.value })} className={inputCls} placeholder="Doe" />
            </Field>
          </div>
          <Field label="LinkedIn URL">
            <input type="url" value={addForm.linkedin_url} onChange={(e) => setAddForm({ ...addForm, linkedin_url: e.target.value })} className={inputCls} placeholder="https://www.linkedin.com/in/jane-doe" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Email">
              <input type="email" value={addForm.email} onChange={(e) => setAddForm({ ...addForm, email: e.target.value })} className={inputCls} placeholder="jane@acme.com" />
            </Field>
            <Field label="Phone">
              <input type="tel" value={addForm.phone} onChange={(e) => setAddForm({ ...addForm, phone: e.target.value })} className={inputCls} placeholder="+1 555 0100" />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Company">
              <input type="text" value={addForm.company} onChange={(e) => setAddForm({ ...addForm, company: e.target.value })} className={inputCls} placeholder="Acme Co." />
            </Field>
            <Field label="Headline">
              <input type="text" value={addForm.headline} onChange={(e) => setAddForm({ ...addForm, headline: e.target.value })} className={inputCls} placeholder="VP of Sales" />
            </Field>
          </div>
          <div className="flex items-center justify-end gap-2 pt-2">
            <Button variant="ghost" size="md" onClick={() => setAddOpen(false)} disabled={adding}>Cancel</Button>
            <Button variant="primary" size="md" icon={UserPlus} onClick={handleAddManual} disabled={adding}>
              {adding ? 'Adding…' : 'Add lead'}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  )
}

const inputCls = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-[13px] text-slate-900 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-slate-700 dark:bg-slate-900 dark:text-white'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{label}</span>
      {children}
    </label>
  )
}

function Pip({ on }: { on: boolean }) {
  return (
    <span
      className={clsx(
        'inline-flex h-1.5 w-4 rounded-full transition-colors',
        on ? 'bg-emerald-500' : 'bg-slate-200 dark:bg-slate-700',
      )}
    />
  )
}
