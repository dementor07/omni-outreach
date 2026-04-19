import { useState } from 'react'
import { ShieldOff, Plus, Search, Trash2, X, Globe, Mail, Linkedin, Building } from 'lucide-react'
import { useBlacklist, useAddBlacklist, useRemoveBlacklist } from '../hooks/useBlacklist'
import { useToast } from '../components/Toast'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'

const ENTRY_TYPES = [
  { key: 'email', label: 'Email', icon: Mail, color: 'text-sky-600 bg-sky-100' },
  { key: 'domain', label: 'Domain', icon: Globe, color: 'text-violet-600 bg-violet-100' },
  { key: 'linkedin_url', label: 'LinkedIn', icon: Linkedin, color: 'text-blue-600 bg-blue-100' },
  { key: 'company', label: 'Company', icon: Building, color: 'text-amber-600 bg-amber-100' },
] as const

export default function Blacklist() {
  const [typeFilter, setTypeFilter] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [addOpen, setAddOpen] = useState(false)
  const [newEntry, setNewEntry] = useState({ entry_type: 'email', value: '', reason: '' })

  const { data, isLoading } = useBlacklist(typeFilter || undefined, search || undefined, page)
  const addBlacklist = useAddBlacklist()
  const removeBlacklist = useRemoveBlacklist()
  const toast = useToast()

  const handleAdd = async () => {
    if (!newEntry.value.trim()) return
    try {
      await addBlacklist.mutateAsync(newEntry)
      toast.success('Added to blacklist')
      setAddOpen(false)
      setNewEntry({ entry_type: 'email', value: '', reason: '' })
    } catch {
      toast.error('Already blacklisted or failed')
    }
  }

  const handleRemove = async (id: string) => {
    await removeBlacklist.mutateAsync(id)
    toast.success('Removed from blacklist')
  }

  const getTypeConfig = (type: string) =>
    ENTRY_TYPES.find((t) => t.key === type) || ENTRY_TYPES[0]

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Blacklist / DNC</h1>
          <p className="mt-1 text-sm text-slate-500">
            Manage blocked emails, domains, LinkedIn profiles, and companies
          </p>
        </div>
        <button
          onClick={() => setAddOpen(true)}
          className="flex items-center gap-2 rounded-xl bg-rose-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-rose-600"
        >
          <Plus size={16} />
          Add entry
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
          <Search size={14} className="text-slate-400" />
          <input
            type="text"
            placeholder="Search blacklist..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
            className="w-full text-sm text-slate-700 outline-none placeholder:text-slate-400"
          />
          {search && (
            <button onClick={() => setSearch('')} className="text-slate-400 hover:text-slate-600">
              <X size={14} />
            </button>
          )}
        </div>
        <div className="flex gap-1 rounded-xl border border-slate-200 bg-white p-1">
          <button
            onClick={() => { setTypeFilter(''); setPage(1) }}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${!typeFilter ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
          >
            All
          </button>
          {ENTRY_TYPES.map((t) => (
            <button
              key={t.key}
              onClick={() => { setTypeFilter(t.key); setPage(1) }}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${typeFilter === t.key ? 'bg-slate-900 text-white' : 'text-slate-500 hover:bg-slate-100'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      {isLoading ? (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-slate-100" />
          ))}
        </div>
      ) : !data?.entries.length ? (
        <EmptyState icon={ShieldOff} title="No blacklist entries" description="Add entries to prevent outreach to specific contacts or domains." />
      ) : (
        <div className="space-y-2">
          {data.entries.map((entry) => {
            const cfg = getTypeConfig(entry.entry_type)
            const Icon = cfg.icon
            return (
              <div key={entry.id} className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white px-4 py-3">
                <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${cfg.color}`}>
                  <Icon size={16} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-slate-900 truncate">{entry.value}</div>
                  <div className="text-xs text-slate-400">
                    {entry.entry_type} {entry.reason && `· ${entry.reason}`}
                  </div>
                </div>
                <span className="text-xs text-slate-400">
                  {new Date(entry.created_at).toLocaleDateString()}
                </span>
                <button
                  onClick={() => handleRemove(entry.id)}
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-500"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Pagination */}
      {data && data.total > 50 && (
        <div className="flex justify-center gap-2">
          <button
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Previous
          </button>
          <span className="flex items-center px-3 text-sm text-slate-500">
            Page {page} of {Math.ceil(data.total / 50)}
          </span>
          <button
            disabled={page >= Math.ceil(data.total / 50)}
            onClick={() => setPage(page + 1)}
            className="rounded-lg border border-slate-200 px-3 py-1.5 text-sm disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}

      {/* Add modal */}
      <Modal title="Add to blacklist" open={addOpen} onClose={() => setAddOpen(false)}>
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Type</label>
            <div className="flex gap-2">
              {ENTRY_TYPES.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setNewEntry({ ...newEntry, entry_type: t.key })}
                  className={`flex-1 rounded-lg border px-3 py-2 text-xs font-medium transition-colors ${newEntry.entry_type === t.key ? 'border-sky-300 bg-sky-50 text-sky-700' : 'border-slate-200 text-slate-500 hover:bg-slate-50'}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Value</label>
            <input
              type="text"
              value={newEntry.value}
              onChange={(e) => setNewEntry({ ...newEntry, value: e.target.value })}
              placeholder={
                newEntry.entry_type === 'email' ? 'user@example.com' :
                newEntry.entry_type === 'domain' ? 'example.com' :
                newEntry.entry_type === 'linkedin_url' ? 'https://linkedin.com/in/...' :
                'Company name'
              }
              className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Reason (optional)</label>
            <input
              type="text"
              value={newEntry.reason}
              onChange={(e) => setNewEntry({ ...newEntry, reason: e.target.value })}
              placeholder="e.g., Requested removal, competitor, etc."
              className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:border-sky-300 focus:ring-2 focus:ring-sky-100"
            />
          </div>
          <button
            onClick={handleAdd}
            disabled={!newEntry.value.trim() || addBlacklist.isPending}
            className="w-full rounded-xl bg-rose-500 py-2.5 text-sm font-semibold text-white hover:bg-rose-600 disabled:opacity-40"
          >
            {addBlacklist.isPending ? 'Adding...' : 'Add to blacklist'}
          </button>
        </div>
      </Modal>
    </div>
  )
}
