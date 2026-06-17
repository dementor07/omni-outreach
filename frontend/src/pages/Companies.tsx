import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Building2, Globe, Layers, Trash2 } from 'lucide-react'
import { projections, type Company } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Avatar from '../components/Avatar'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput } from '../components/FilterBar'
import { useToast } from '../components/Toast'

export default function Companies() {
  const qc = useQueryClient()
  const toast = useToast()
  const { data: companies = [], isLoading } = useQuery({
    queryKey: ['companies'],
    queryFn: () => projections.companies(500),
  })

  const delMut = useMutation({
    mutationFn: projections.deleteCompany,
    onSuccess: () => {
      toast.success('Company deleted')
      qc.invalidateQueries({ queryKey: ['companies'] })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not delete company'),
  })

  function onDelete(c: Company) {
    if (window.confirm(`Delete ${c.name}? This can't be undone.`)) {
      delMut.mutate(c.id)
    }
  }

  const [search, setSearch] = useState('')
  const filtered = useMemo(() => filterCompanies(companies, search), [companies, search])
  const withDomain = companies.filter((c) => c.domain).length
  const industries = new Set(companies.map((c) => c.industry).filter(Boolean)).size

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Companies"
        eyebrow="CRM"
        title="Companies"
        description="Accounts in your CRM — the organisations your contacts belong to."
      />

      <section className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Total companies" value={isLoading ? '—' : companies.length} icon={Building2} accent="brand" />
        <StatCard label="With domain" value={isLoading ? '—' : withDomain} icon={Globe} accent="emerald" />
        <StatCard label="Industries" value={isLoading ? '—' : industries} icon={Layers} accent="violet" />
      </section>

      <FilterBar>
        <SearchInput placeholder="Search by name, domain, industry…" value={search} onChange={setSearch} />
      </FilterBar>

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : filtered.length === 0 ? (
        <Card><EmptyState icon={Building2} title={search ? 'No matches' : 'No companies yet'} description={search ? 'Try a different search.' : 'Companies appear when enrichment or imports create them.'} /></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((c) => <CompanyCard key={c.id} c={c} onDelete={onDelete} deleting={delMut.isPending} />)}
        </div>
      )}
    </div>
  )
}

interface CompanyCardProps {
  c: Company
  onDelete: (c: Company) => void
  deleting: boolean
}

function CompanyCard({ c, onDelete, deleting }: CompanyCardProps) {
  return (
    <Card padding="md" className="group relative">
      <button
        type="button"
        onClick={() => onDelete(c)}
        disabled={deleting}
        title="Delete company"
        aria-label="Delete company"
        className="absolute right-2 top-2 rounded p-1.5 text-slate-400 opacity-0 transition-colors hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 dark:hover:bg-rose-900/30"
      >
        <Trash2 size={15} />
      </button>
      <div className="flex items-start gap-3">
        <Avatar name={c.name} size={40} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{c.name}</p>
          {c.domain && (
            <a href={`https://${c.domain}`} target="_blank" rel="noreferrer" className="truncate text-xs text-brand-600 hover:underline">
              {c.domain}
            </a>
          )}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {c.industry && <Badge label={c.industry} variant="info" size="xs" />}
        {c.size && <Badge label={c.size} variant="neutral" size="xs" />}
      </div>
    </Card>
  )
}

function filterCompanies(list: Company[], q: string): Company[] {
  if (!q.trim()) return list
  const needle = q.toLowerCase()
  return list.filter((c) => [c.name, c.domain, c.industry].filter(Boolean).join(' ').toLowerCase().includes(needle))
}
