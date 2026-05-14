import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users, Activity, MessageSquare, X as XIcon, Plus, ArrowUpRight, MoreHorizontal, ChevronRight, Megaphone } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import DataTable from '../components/DataTable'
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
  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const [campaignId, setCampaignId] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')

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
            <Button variant="secondary" size="md" icon={ArrowUpRight}>Export CSV</Button>
            <Button variant="primary" size="md" icon={Plus}>Add leads</Button>
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
            action={<Button variant="primary" size="sm" icon={Plus}>Add leads</Button>}
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
    </div>
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
