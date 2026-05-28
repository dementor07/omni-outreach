import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Users, Activity, MessageSquare, Flame } from 'lucide-react'
import { clsx } from 'clsx'
import { projections, ai, type Lead, type LeadScore } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'

export default function Leads() {
  const { data: leads = [], isLoading } = useQuery({
    queryKey: ['leads'],
    queryFn: () => projections.leads({ limit: 1000 }),
  })
  const { data: scores = [] } = useQuery({ queryKey: ['lead-scores'], queryFn: () => ai.scores({ limit: 1000 }) })

  const scoreByLead = useMemo(() => {
    const m = new Map<string, LeadScore>()
    for (const s of scores) m.set(s.lead_id, s)
    return m
  }, [scores])

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')

  const filtered = useMemo(() => {
    let out = leads
    if (status) out = out.filter((l) => l.status === status)
    if (search) {
      const q = search.toLowerCase()
      out = out.filter((l) => l.id.toLowerCase().includes(q) || (l.contact_id ?? '').toLowerCase().includes(q))
    }
    // sort by AI score desc when available
    return [...out].sort((a, b) => (scoreByLead.get(b.id)?.score ?? -1) - (scoreByLead.get(a.id)?.score ?? -1))
  }, [leads, status, search, scoreByLead])

  const active = leads.filter((l) => l.status === 'active').length
  const replied = leads.filter((l) => l.status === 'replied').length
  const stopped = leads.filter((l) => l.status === 'stopped').length
  const hot = scores.filter((s) => s.tier === 'hot').length

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Leads"
        eyebrow="Pipeline"
        title="Leads"
        description="Every prospect in flight, ranked by AI ICP fit. Hottest first."
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total" value={isLoading ? '—' : leads.length} icon={Users} accent="brand" />
        <StatCard label="Active" value={isLoading ? '—' : active} icon={Activity} accent="emerald" />
        <StatCard label="Replied" value={isLoading ? '—' : replied} icon={MessageSquare} accent="violet" />
        <StatCard label="Hot (AI)" value={hot} icon={Flame} accent="rose" hint="ICP score ≥ 70" />
      </section>

      <FilterBar>
        <SearchInput placeholder="Search by lead or contact id…" value={search} onChange={setSearch} />
        <Select value={status} onChange={setStatus}>
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="replied">Replied</option>
          <option value="stopped">Stopped</option>
        </Select>
      </FilterBar>

      <Card padding="none">
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={Users} title={search || status ? 'No matches' : 'No leads yet'} description={search || status ? 'Adjust your filters.' : 'Leads appear when a source node imports prospects into a workflow.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wider text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2.5 font-medium">AI score</th>
                  <th className="px-4 py-2.5 font-medium">Lead</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 font-medium">Why (AI)</th>
                  <th className="px-4 py-2.5 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.map((l) => (
                  <LeadRow key={l.id} lead={l} score={scoreByLead.get(l.id)} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function LeadRow({ lead, score }: { lead: Lead; score?: LeadScore }) {
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
      <td className="px-4 py-2.5">
        <p className="font-medium text-slate-900 dark:text-white">Lead {lead.id.slice(0, 8)}</p>
        <p className="text-xs text-slate-500">{lead.contact_id ? `contact ${lead.contact_id.slice(0, 8)}` : 'no contact'}</p>
      </td>
      <td className="px-4 py-2.5"><Badge label={lead.status} asStatus dot /></td>
      <td className="max-w-xs px-4 py-2.5 text-xs text-slate-500">{score?.reasons[0] ?? '—'}</td>
      <td className="px-4 py-2.5 text-slate-400">{new Date(lead.updated_at).toLocaleDateString()}</td>
    </tr>
  )
}
