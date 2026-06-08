import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users, Activity, Building2, Flame, ExternalLink } from 'lucide-react'
import { clsx } from 'clsx'
import { projections, ai, canvas, type Lead, type LeadScore, type LeadColumn } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'

// A lead's displayable fields are additive per node, so the table columns are
// driven by the selected workflow's node graph (GET /projections/leads/columns).
// "All workflows" falls back to the universal identity/stage/status columns.
export default function Leads() {
  const [workflowId, setWorkflowId] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')

  const { data: workflows = [] } = useQuery({ queryKey: ['workflows'], queryFn: canvas.list })
  const { data: leads = [], isLoading } = useQuery({
    queryKey: ['leads', workflowId],
    queryFn: () => projections.leads({ workflow_id: workflowId || undefined, limit: 1000 }),
  })
  const { data: columnsResp } = useQuery({
    queryKey: ['lead-columns', workflowId],
    queryFn: () => projections.leadColumns(workflowId || undefined),
  })
  const { data: scores = [] } = useQuery({ queryKey: ['lead-scores'], queryFn: () => ai.scores({ limit: 1000 }) })

  const columns = columnsResp?.columns ?? []
  const scoreByLead = useMemo(() => {
    const m = new Map<string, LeadScore>()
    for (const s of scores) m.set(s.lead_id, s)
    return m
  }, [scores])

  const filtered = useMemo(() => {
    let out = leads
    if (status) out = out.filter((l) => l.status === status)
    if (search) {
      const q = search.toLowerCase()
      out = out.filter((l) => l.identity.toLowerCase().includes(q) || l.id.toLowerCase().includes(q))
    }
    return [...out].sort((a, b) => (scoreByLead.get(b.id)?.score ?? -1) - (scoreByLead.get(a.id)?.score ?? -1))
  }, [leads, status, search, scoreByLead])

  const persons = leads.filter((l) => l.stage === 'person').length
  const companies = leads.filter((l) => l.stage === 'company' || l.stage === 'resolved').length
  const hot = scores.filter((s) => s.tier === 'hot').length

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Leads"
        eyebrow="Pipeline"
        title="Leads"
        description="Every prospect in flight. Columns adapt to the selected workflow's pipeline."
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total" value={isLoading ? '—' : leads.length} icon={Users} accent="brand" />
        <StatCard label="People" value={isLoading ? '—' : persons} icon={Activity} accent="emerald" hint="Resolved to a contact" />
        <StatCard label="Companies" value={isLoading ? '—' : companies} icon={Building2} accent="violet" hint="Discovered, awaiting people" />
        <StatCard label="Hot (AI)" value={hot} icon={Flame} accent="rose" hint="ICP score ≥ 70" />
      </section>

      <FilterBar>
        <Select value={workflowId} onChange={setWorkflowId}>
          <option value="">All workflows</option>
          {workflows.map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </Select>
        <SearchInput placeholder="Search leads…" value={search} onChange={setSearch} />
        <Select value={status} onChange={setStatus}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="waiting">Waiting</option>
          <option value="replied">Replied</option>
          <option value="converted">Converted</option>
          <option value="completed">Completed</option>
          <option value="ended">Ended</option>
          <option value="stopped">Stopped</option>
          <option value="errored">Errored</option>
        </Select>
      </FilterBar>

      <Card padding="none">
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={Users}
            title={search || status ? 'No matches' : 'No leads yet'}
            description={search || status ? 'Adjust your filters.' : 'Leads appear when a source node imports prospects into a workflow. Run a workflow from the canvas to populate this view.'}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wider text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2.5 font-medium">AI</th>
                  {columns.map((c) => (
                    <th key={c.key} className="px-4 py-2.5 font-medium">{c.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.map((l) => (
                  <LeadRow key={l.id} lead={l} columns={columns} score={scoreByLead.get(l.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

interface LeadRowProps {
  lead: Lead
  columns: LeadColumn[]
  score?: LeadScore
}

function LeadRow({ lead, columns, score }: LeadRowProps) {
  return (
    <tr className="hover:bg-slate-50 dark:hover:bg-slate-900/50">
      <td className="px-4 py-2.5">
        {score ? (
          <span className={clsx(
            'inline-flex h-8 w-8 items-center justify-center rounded-lg text-sm font-bold tabular-nums',
            score.tier === 'hot' ? 'bg-rose-50 text-rose-600' : score.tier === 'warm' ? 'bg-amber-50 text-amber-600' : 'bg-slate-100 text-slate-500',
          )}>
            {score.score}
          </span>
        ) : (
          <span className="text-xs text-slate-300">—</span>
        )}
      </td>
      {columns.map((c) => (
        <LeadCell key={c.key} column={c} lead={lead} />
      ))}
    </tr>
  )
}

function LeadCell({ column, lead }: { column: LeadColumn; lead: Lead }) {
  // identity/stage/status/updated_at are computed top-level fields; every other
  // column comes from the flattened per-workflow ``fields`` bag the backend
  // resolved from the lead's custom_fields + joined contact.
  if (column.key === 'identity') {
    return (
      <td className="px-4 py-2.5">
        <p className="font-medium text-slate-900 dark:text-white">{lead.identity}</p>
        <p className="text-xs text-slate-500">{stageHint(lead)}</p>
      </td>
    )
  }

  const value =
    column.key === 'stage' ? lead.stage
    : column.key === 'status' ? lead.status
    : column.key === 'updated_at' ? lead.updated_at
    : lead.fields[column.key]

  if (column.kind === 'badge') {
    return <td className="px-4 py-2.5">{value != null && value !== '' ? <Badge label={String(value)} asStatus dot /> : <span className="text-slate-300">—</span>}</td>
  }
  if (column.kind === 'date') {
    return <td className="px-4 py-2.5 text-slate-400">{value ? new Date(String(value)).toLocaleDateString() : '—'}</td>
  }
  if (column.kind === 'url') {
    const url = value ? String(value) : ''
    return (
      <td className="px-4 py-2.5">
        {url ? (
          <a href={url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">
            <ExternalLink size={13} /> open
          </a>
        ) : (
          <span className="text-slate-300">—</span>
        )}
      </td>
    )
  }
  if (column.kind === 'number') {
    return <td className="px-4 py-2.5 tabular-nums text-slate-600 dark:text-slate-300">{value != null && value !== '' ? String(value) : '—'}</td>
  }
  return <td className="max-w-xs truncate px-4 py-2.5 text-slate-600 dark:text-slate-300">{value != null && value !== '' ? String(value) : '—'}</td>
}

function stageHint(lead: Lead): string {
  switch (lead.stage) {
    case 'person': return lead.contact_id ? 'contact' : 'person'
    case 'company': return 'company stage'
    case 'resolved': return 'company resolved'
    case 'verifying': return 'verifying person'
    case 'source': return 'source batch'
    default: return lead.stage
  }
}
