import { useState, useMemo } from 'react'
import { useQuery, useMutation as useRQMutation } from '@tanstack/react-query'
import { ShieldOff, Mail, Database, Users, Plus, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card, { CardHeader } from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import DataTable from '../components/DataTable'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'
import { timeAgo, buildQuery } from '../lib/format'

interface BLEntry { id: string; entry_type: string; value: string; reason?: string; created_at: string }

export default function Blacklist() {
  const [entryType, setEntryType] = useState('')
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [form, setForm] = useState({ entry_type: 'email', value: '', reason: '' })

  const blacklistQ = useQuery<{ entries: BLEntry[]; total: number }>({
    queryKey: ['blacklist', entryType, search],
    queryFn: () => api.get(`/blacklist${buildQuery({ entry_type: entryType, search, page_size: 100 })}`).then(r => r.data),
  })

  const addM = useRQMutation({
    mutationFn: (body: { entry_type: string; value: string; reason: string }) => api.post('/blacklist', body),
    onSuccess: () => { setForm({ entry_type: 'email', value: '', reason: '' }); setShowAdd(false); blacklistQ.refetch() },
  })

  const removeM = useRQMutation({
    mutationFn: (id: string) => api.delete(`/blacklist/${id}`),
    onSuccess: () => blacklistQ.refetch(),
  })

  const entries = blacklistQ.data?.entries || []
  const total = blacklistQ.data?.total ?? 0

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    entries.forEach(e => { c[e.entry_type] = (c[e.entry_type] || 0) + 1 })
    return c
  }, [entries])

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Blacklist"
        eyebrow="Safety"
        title="Blacklist"
        description="Emails, domains, profiles, and companies your sequencer must never contact. Checked on every lead intake."
        actions={<Button variant="primary" size="md" icon={Plus} onClick={() => setShowAdd(v => !v)}>Add entry</Button>}
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total entries" value={blacklistQ.isLoading ? '—' : total} icon={ShieldOff} accent="slate" />
        <StatCard label="Emails" value={blacklistQ.isLoading ? '—' : (counts.email ?? 0)} icon={Mail} accent="brand" />
        <StatCard label="Domains" value={blacklistQ.isLoading ? '—' : (counts.domain ?? 0)} icon={Database} accent="violet" />
        <StatCard label="Profiles & companies" value={blacklistQ.isLoading ? '—' : ((counts.linkedin_url ?? 0) + (counts.company ?? 0))} icon={Users} accent="amber" />
      </section>

      {showAdd && (
        <Card padding="lg">
          <CardHeader title="New blacklist entry" description="Will block future intake immediately." />
          <div className="grid gap-3 md:grid-cols-[180px_1fr_1fr_auto]">
            <Select value={form.entry_type} onChange={v => setForm({ ...form, entry_type: v })}>
              <option value="email">Email</option>
              <option value="domain">Domain</option>
              <option value="linkedin_url">LinkedIn URL</option>
              <option value="company">Company</option>
            </Select>
            <input
              type="text"
              value={form.value}
              onChange={e => setForm({ ...form, value: e.target.value })}
              placeholder={form.entry_type === 'email' ? 'name@example.com' : form.entry_type === 'domain' ? 'example.com' : 'Value'}
              className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
            <input
              type="text"
              value={form.reason}
              onChange={e => setForm({ ...form, reason: e.target.value })}
              placeholder="Reason (optional)"
              className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
            />
            <div className="flex items-center gap-2">
              <Button variant="primary" size="md" onClick={() => addM.mutate(form)} disabled={addM.isPending || !form.value.trim()}>
                {addM.isPending ? 'Adding…' : 'Add'}
              </Button>
              <Button variant="ghost" size="md" onClick={() => setShowAdd(false)}>Cancel</Button>
            </div>
          </div>
        </Card>
      )}

      <FilterBar>
        <SearchInput placeholder="Search entries…" value={search} onChange={setSearch} />
        <Select value={entryType} onChange={setEntryType}>
          <option value="">All types</option>
          <option value="email">Email</option>
          <option value="domain">Domain</option>
          <option value="linkedin_url">LinkedIn URL</option>
          <option value="company">Company</option>
        </Select>
      </FilterBar>

      <Card padding="none">
        {blacklistQ.isLoading ? (
          <div className="space-y-1 p-4">{[0,1,2,3].map(i => <div key={i} className="h-10 skeleton" />)}</div>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={ShieldOff}
            title="No blacklist entries"
            description="Block emails, domains, LinkedIn profiles, or companies from ever entering your sequences."
            action={<Button variant="primary" size="sm" icon={Plus} onClick={() => setShowAdd(true)}>Add entry</Button>}
          />
        ) : (
          <DataTable
            columns={[
              { key: 'entry_type', header: 'Type', render: (row: BLEntry) => <Badge label={row.entry_type} variant="neutral" /> },
              { key: 'value', header: 'Value', render: (row: BLEntry) => <span className="font-mono text-[13px] text-slate-700 dark:text-slate-200">{row.value}</span> },
              { key: 'reason', header: 'Reason', render: (row: BLEntry) => <span className="text-slate-500">{row.reason || <span className="text-slate-300">—</span>}</span> },
              { key: 'created_at', header: 'Added', render: (row: BLEntry) => <span className="text-xs tabular-nums text-slate-500">{timeAgo(row.created_at)}</span> },
              { key: 'actions', header: '', align: 'right' as const, render: (row: BLEntry) => <Button variant="ghost" size="sm" icon={Trash2} onClick={() => { if (confirm('Remove?')) removeM.mutate(row.id) }} /> },
            ]}
            rows={entries}
          />
        )}
      </Card>
    </div>
  )
}
