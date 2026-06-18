import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Database, Search, ExternalLink } from 'lucide-react'
import { nodes, integrations, sources, type NodeManifest, type NaukriPreviewCompany } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import Select from '../components/Select'

export default function LeadSources() {
  const nodesQ = useQuery({ queryKey: ['node-manifests'], queryFn: nodes.list })
  const connsQ = useQuery({ queryKey: ['connections'], queryFn: () => integrations.list() })

  // NodeCategory is lowercase on the wire ("source") — compare case-insensitively.
  const sourceNodes = (nodesQ.data ?? []).filter((m) => m.category.toUpperCase() === 'SOURCE')
  const connectedProviders = new Set((connsQ.data ?? []).map((c) => c.provider))
  const hasNaukri = sourceNodes.some((s) => s.type === 'source.naukri')

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Lead Sources"
        eyebrow="Setup"
        title="Lead Sources"
        description="Where your leads come from. Each source is a node you can drop into a campaign."
      />

      {hasNaukri && <NaukriPreviewPanel />}

      {nodesQ.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : sourceNodes.length === 0 ? (
        <Card><EmptyState icon={Database} title="No source nodes registered" description="Source nodes (Apollo, Hunter, Sheets, …) will appear here." /></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sourceNodes.map((s) => <SourceCard key={s.type} s={s} connected={isConnected(s.type, connectedProviders)} />)}
        </div>
      )}
    </div>
  )
}

function isConnected(nodeType: string, providers: Set<string>): boolean {
  // node type is like "source.apollo" → provider "apollo"
  const provider = nodeType.split('.')[1]
  return provider ? providers.has(provider) : false
}

function SourceCard({ s, connected }: { s: NodeManifest; connected: boolean }) {
  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-900/30">
          <Database size={16} />
        </span>
        <Badge label={connected ? 'connected' : 'not connected'} variant={connected ? 'success' : 'neutral'} size="xs" dot />
      </div>
      <p className="mt-3 text-sm font-semibold text-slate-900 dark:text-white">{s.type}</p>
      <p className="mt-0.5 text-xs text-slate-500">{s.summary}</p>
    </Card>
  )
}

// DataTable infers its row type T (constrained to { id?: string }) from `rows`.
// Give each preview company a stable id so T binds to this shape, not the bare
// constraint, and the column render callbacks stay fully typed.
type CompanyRow = NaukriPreviewCompany & { id: string }

function NaukriPreviewPanel() {
  const [keyword, setKeyword] = useState('')
  const [location, setLocation] = useState('')
  const [maxPages, setMaxPages] = useState(1)

  const preview = useMutation({
    mutationFn: () => sources.naukriPreview({ keyword: keyword.trim(), location: location.trim() || null, max_pages: maxPages }),
  })

  const canRun = keyword.trim().length > 0 && !preview.isPending
  const result = preview.data
  const rows: CompanyRow[] = (result?.companies ?? []).map((c, i) => ({ ...c, id: `${c.company_name}-${i}` }))
  const errorMessage = preview.isError
    ? ((preview.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Preview failed — is the scraper reachable?')
    : null

  function run(e: React.FormEvent) {
    e.preventDefault()
    if (canRun) preview.mutate()
  }

  return (
    <Card padding="md">
      <div className="flex items-center gap-2">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-50 text-violet-600 dark:bg-violet-900/30">
          <Search size={15} />
        </span>
        <div>
          <p className="text-sm font-semibold text-slate-900 dark:text-white">Naukri scrape preview</p>
          <p className="text-xs text-slate-500">Dry-run a keyword to see which hiring companies it returns — no campaign, no leads created.</p>
        </div>
      </div>

      <form onSubmit={run} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
          Role keyword
          <input
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="e.g. SDR"
            className="h-9 w-48 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
          Location <span className="text-slate-400">(optional)</span>
          <input
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="e.g. India"
            className="h-9 w-40 rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
          Pages
          <Select
            className="w-20"
            ariaLabel="Pages to scrape"
            value={String(maxPages)}
            onChange={(v) => setMaxPages(Number(v))}
            options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))}
          />
        </label>
        <Button type="submit" variant="primary" icon={Search} isLoading={preview.isPending} disabled={!canRun}>
          Preview
        </Button>
      </form>

      {errorMessage && (
        <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-600 dark:bg-rose-950/40 dark:text-rose-300">{errorMessage}</p>
      )}

      {result && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-slate-500">
            <span className="font-semibold text-slate-700 dark:text-slate-300">{result.companies_extracted}</span> companies
            {' '}from <span className="font-semibold text-slate-700 dark:text-slate-300">{result.jobs_returned}</span> postings for “{result.keyword}”
          </p>
          <DataTable<CompanyRow>
            columns={[
              { key: 'company_name', header: 'Company', render: (c) => <span className="font-medium text-slate-900 dark:text-white">{c.company_name}</span> },
              { key: 'title', header: 'Sample role' },
              { key: 'role_count', header: 'Roles', align: 'right' },
              { key: 'location', header: 'Location' },
              { key: 'experience', header: 'Experience' },
              {
                key: 'source_url',
                header: 'Source',
                render: (c) =>
                  c.source_url ? (
                    <a href={c.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-brand-600 hover:underline">
                      <ExternalLink size={13} /> open
                    </a>
                  ) : <span className="text-slate-400">—</span>,
              },
            ]}
            rows={rows}
            emptyMessage="No companies returned for this keyword."
          />
        </div>
      )}
    </Card>
  )
}
