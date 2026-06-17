import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Contact as ContactIcon, Mail, Building2, AtSign, Users, Trash2 } from 'lucide-react'
import { projections, type Contact } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Avatar from '../components/Avatar'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput } from '../components/FilterBar'
import { useToast } from '../components/Toast'
import { fullName } from '../lib/format'

export default function Contacts() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const { data: contacts = [], isLoading } = useQuery({
    queryKey: ['contacts'],
    queryFn: () => projections.contacts(500),
  })

  const delMut = useMutation({
    mutationFn: projections.deleteContact,
    onSuccess: () => {
      toast.success('Contact deleted')
      qc.invalidateQueries({ queryKey: ['contacts'] })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not delete contact'),
  })

  function onDelete(e: React.MouseEvent, c: Contact) {
    e.stopPropagation()
    if (window.confirm(`Delete ${fullName(c) || c.email || 'this contact'}? This can't be undone.`)) {
      delMut.mutate(c.id)
    }
  }

  const [search, setSearch] = useState('')
  const filtered = useMemo(() => filterContacts(contacts, search), [contacts, search])

  const withEmail = contacts.filter((c) => c.email).length
  const withLinkedin = contacts.filter((c) => c.linkedin_url).length
  const withCompany = contacts.filter((c) => c.company).length

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Contacts"
        eyebrow="CRM"
        title="Contacts"
        description="Every person in your CRM, enriched and deduplicated from all your sources."
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total contacts" value={isLoading ? '—' : contacts.length} icon={Users} accent="brand" />
        <StatCard label="With email" value={isLoading ? '—' : withEmail} icon={Mail} accent="emerald" />
        <StatCard label="With LinkedIn" value={isLoading ? '—' : withLinkedin} icon={AtSign} accent="violet" />
        <StatCard label="With company" value={isLoading ? '—' : withCompany} icon={Building2} accent="amber" />
      </section>

      <FilterBar>
        <SearchInput placeholder="Search by name, email, company…" value={search} onChange={setSearch} />
      </FilterBar>

      <Card padding="none">
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
        ) : filtered.length === 0 ? (
          <EmptyState icon={ContactIcon} title={search ? 'No matches' : 'No contacts yet'} description={search ? 'Try a different search.' : 'Contacts appear once a workflow or import creates them.'} />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wider text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Title</th>
                  <th className="px-4 py-2.5 font-medium">Company</th>
                  <th className="px-4 py-2.5 font-medium">Source</th>
                  <th className="px-4 py-2.5 font-medium">Updated</th>
                  <th className="px-4 py-2.5 font-medium sr-only">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => navigate(`/contacts/${c.id}`)}
                    className="group cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-900/50"
                  >
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
                        onClick={(e) => onDelete(e, c)}
                        disabled={delMut.isPending}
                        title="Delete contact"
                        aria-label="Delete contact"
                        className="rounded p-1.5 text-slate-400 opacity-0 transition-colors hover:bg-rose-50 hover:text-rose-600 group-hover:opacity-100 dark:hover:bg-rose-900/30"
                      >
                        <Trash2 size={15} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function filterContacts(list: Contact[], q: string): Contact[] {
  if (!q.trim()) return list
  const needle = q.toLowerCase()
  return list.filter((c) =>
    [c.first_name, c.last_name, c.email, c.company, c.headline].filter(Boolean).join(' ').toLowerCase().includes(needle),
  )
}
