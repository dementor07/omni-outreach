import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Contact as ContactIcon, Mail, Building2, AtSign, Users, Trash2, Download } from 'lucide-react'
import { projections, canvas, type Contact } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Avatar from '../components/Avatar'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'
import { useToast } from '../components/Toast'
import { useDebounce } from '../hooks/useDebounce'
import { fullName } from '../lib/format'
import { downloadCsv, type CsvColumn } from '../lib/csv'

const CSV_COLUMNS: CsvColumn<Contact>[] = [
  { header: 'First name', value: (c) => c.first_name },
  { header: 'Last name', value: (c) => c.last_name },
  { header: 'Email', value: (c) => c.email },
  { header: 'Title', value: (c) => c.headline },
  { header: 'Company', value: (c) => c.company },
  { header: 'LinkedIn', value: (c) => c.linkedin_url },
  { header: 'Phone', value: (c) => c.phone },
  { header: 'Source', value: (c) => c.source },
]

export default function Contacts() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()

  const [search, setSearch] = useState('')
  const [campaign, setCampaign] = useState('') // workflow_id or ''
  const [source, setSource] = useState('')
  const [emailOnly, setEmailOnly] = useState('') // '', 'yes', 'no'
  const debouncedSearch = useDebounce(search, 300)

  const filters = useMemo(
    () => ({
      limit: 500,
      ...(debouncedSearch.trim() ? { q: debouncedSearch.trim() } : {}),
      ...(campaign ? { workflow_id: campaign } : {}),
      ...(source ? { source } : {}),
      ...(emailOnly === 'yes' ? { has_email: true } : emailOnly === 'no' ? { has_email: false } : {}),
    }),
    [debouncedSearch, campaign, source, emailOnly],
  )

  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ['contacts', filters],
    queryFn: () => projections.contacts(filters),
  })
  const summaryFilters = useMemo(() => {
    return {
      q: filters.q,
      source: filters.source,
      workflow_id: filters.workflow_id,
      has_email: filters.has_email,
    }
  }, [filters])
  const summaryQ = useQuery({
    queryKey: ['contacts-summary', summaryFilters],
    queryFn: () => projections.contactSummary(summaryFilters),
  })
  // Filter-option sources for the dropdowns.
  const campaignsQ = useQuery({ queryKey: ['campaigns-list'], queryFn: canvas.list })
  const sourcesQ = useQuery({ queryKey: ['contact-sources'], queryFn: projections.contactSources })

  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Server already filtered; `filtered` is the rendered set.
  const filtered = contacts
  const anyFilter = !!(debouncedSearch.trim() || campaign || source || emailOnly)

  // Selection is scoped to what's currently visible — clear stale ids on filter.
  const visibleIds = useMemo(() => new Set(filtered.map((c) => c.id)), [filtered])
  const selectedVisible = useMemo(
    () => [...selected].filter((id) => visibleIds.has(id)),
    [selected, visibleIds],
  )
  const allVisibleSelected = filtered.length > 0 && selectedVisible.length === filtered.length

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    setSelected(allVisibleSelected ? new Set() : new Set(filtered.map((c) => c.id)))
  }

  const delMut = useMutation({
    mutationFn: projections.deleteContact,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['contacts'] }),
  })

  async function deleteMany(ids: string[]) {
    let ok = 0
    for (const id of ids) {
      try {
        await delMut.mutateAsync(id)
        ok += 1
      } catch {
        /* counted below */
      }
    }
    setSelected(new Set())
    if (ok === ids.length) toast.success(`Deleted ${ok} contact${ok === 1 ? '' : 's'}`)
    else toast.error(`Deleted ${ok} of ${ids.length} — ${ids.length - ok} failed`)
  }

  function onDeleteOne(e: React.MouseEvent, c: Contact) {
    e.stopPropagation()
    if (window.confirm(`Delete ${fullName(c) || c.email || 'this contact'}? This can't be undone.`)) {
      deleteMany([c.id])
    }
  }

  function onBulkDelete() {
    const ids = selectedVisible
    if (ids.length && window.confirm(`Delete ${ids.length} selected contact${ids.length === 1 ? '' : 's'}? This can't be undone.`)) {
      deleteMany(ids)
    }
  }

  function exportCsv(rows: Contact[]) {
    if (!rows.length) {
      toast.error('Nothing to export')
      return
    }
    downloadCsv('contacts', rows, CSV_COLUMNS)
    toast.success(`Exported ${rows.length} contact${rows.length === 1 ? '' : 's'}`)
  }

  const summary = summaryQ.data

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Contacts"
        eyebrow="CRM"
        title="Contacts"
        description="Every person in your CRM, enriched and deduplicated from all your sources."
        meta={
          contacts.length > 0 ? (
            <button
              type="button"
              onClick={() => exportCsv(filtered)}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-slate-100 px-3 text-xs font-semibold text-slate-600 transition-colors hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-300"
            >
              <Download size={13} /> Export CSV
            </button>
          ) : null
        }
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label={anyFilter ? 'Matching contacts' : 'Total contacts'} value={summaryQ.isLoading ? '—' : summary?.total ?? 0} icon={Users} accent="brand" />
        <StatCard label="With email" value={summaryQ.isLoading ? '—' : summary?.with_email ?? 0} icon={Mail} accent="emerald" />
        <StatCard label="With LinkedIn" value={summaryQ.isLoading ? '—' : summary?.with_linkedin ?? 0} icon={AtSign} accent="violet" />
        <StatCard label="With company" value={summaryQ.isLoading ? '—' : summary?.with_company ?? 0} icon={Building2} accent="amber" />
      </section>

      <FilterBar>
        <SearchInput placeholder="Search by name, email, company…" value={search} onChange={setSearch} />
        <Select value={campaign} onChange={setCampaign}>
          <option value="">All campaigns</option>
          {(campaignsQ.data ?? []).map((w) => (
            <option key={w.id} value={w.id}>{w.name}</option>
          ))}
        </Select>
        <Select value={source} onChange={setSource}>
          <option value="">All sources</option>
          {(sourcesQ.data ?? []).map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </Select>
        <Select value={emailOnly} onChange={setEmailOnly}>
          <option value="">Email: any</option>
          <option value="yes">Has email</option>
          <option value="no">No email</option>
        </Select>
        {anyFilter && (
          <button
            type="button"
            onClick={() => { setSearch(''); setCampaign(''); setSource(''); setEmailOnly('') }}
            className="h-9 rounded-lg px-3 text-xs font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
          >
            Clear
          </button>
        )}
      </FilterBar>

      {/* Bulk action bar — appears only when something is selected. */}
      {selectedVisible.length > 0 && (
        <div className="flex items-center justify-between rounded-xl border border-brand-200 bg-brand-50 px-4 py-2.5 dark:border-brand-900/50 dark:bg-brand-900/20">
          <span className="text-sm font-medium text-brand-800 dark:text-brand-200">
            {selectedVisible.length} selected
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => exportCsv(filtered.filter((c) => selected.has(c.id)))}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50 dark:bg-slate-800 dark:text-slate-200"
            >
              <Download size={13} /> Export
            </button>
            <button
              type="button"
              onClick={onBulkDelete}
              disabled={delMut.isPending}
              className="inline-flex h-8 items-center gap-1.5 rounded-md bg-rose-600 px-3 text-xs font-semibold text-white hover:bg-rose-700 disabled:opacity-60"
            >
              <Trash2 size={13} /> {delMut.isPending ? 'Deleting…' : 'Delete'}
            </button>
          </div>
        </div>
      )}

      <Card padding="none" className="overflow-hidden">
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={ContactIcon} title={anyFilter ? 'No matches' : 'No contacts yet'} description={anyFilter ? 'Try clearing or changing the filters.' : 'Contacts appear once a workflow or import creates them.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wider text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleAll}
                      aria-label="Select all contacts"
                      className="h-4 w-4 cursor-pointer rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                  </th>
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Title</th>
                  <th className="px-4 py-2.5 font-medium">Company</th>
                  <th className="px-4 py-2.5 font-medium">Source</th>
                  <th className="px-4 py-2.5 font-medium">Updated</th>
                  <th className="px-4 py-2.5 font-medium sr-only">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.map((c) => {
                  const isSelected = selected.has(c.id)
                  return (
                    <tr
                      key={c.id}
                      onClick={() => navigate(`/contacts/${c.id}`)}
                      className={
                        'group cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-900/50' +
                        (isSelected ? ' bg-brand-50/60 dark:bg-brand-900/10' : '')
                      }
                    >
                      <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleOne(c.id)}
                          aria-label={`Select ${fullName(c) || c.email || 'contact'}`}
                          className="h-4 w-4 cursor-pointer rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                        />
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2.5">
                          <Avatar name={fullName(c) || c.email || 'Unknown'} size={30} />
                          <div className="min-w-0">
                            <p className="truncate font-medium text-slate-900 dark:text-white">{fullName(c) || '—'}</p>
                            <p className="truncate text-xs text-slate-500">{c.email ?? c.linkedin_url ?? '—'}</p>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">{c.headline ?? '—'}</td>
                      <td className="px-4 py-2.5 text-slate-600 dark:text-slate-300">{c.company ?? '—'}</td>
                      <td className="px-4 py-2.5">{c.source ? <Badge label={c.source} variant="neutral" size="xs" /> : '—'}</td>
                      <td className="px-4 py-2.5 text-slate-400">{new Date(c.updated_at).toLocaleDateString()}</td>
                      <td className="px-4 py-2.5 text-right">
                        <button
                          type="button"
                          onClick={(e) => onDeleteOne(e, c)}
                          disabled={delMut.isPending}
                          title="Delete contact"
                          aria-label="Delete contact"
                          className="rounded p-1.5 text-slate-400 opacity-0 transition-colors hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 dark:hover:bg-rose-900/30"
                        >
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
