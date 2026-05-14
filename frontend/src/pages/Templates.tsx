import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Edit2, Trash2, Plus, Sparkles, FileText } from 'lucide-react'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput, Select } from '../components/FilterBar'
import ChannelIcon from '../components/ChannelIcon'

interface Template { id: string; name: string; channel: string; category: string; subject?: string; body: string; variables?: string[] }

const CHANNELS = [
  { key: 'email', label: 'Email' },
  { key: 'linkedin_dm', label: 'LinkedIn DM' },
  { key: 'linkedin_inmail', label: 'InMail' },
  { key: 'whatsapp', label: 'WhatsApp' },
  { key: 'sms', label: 'SMS' },
]
const CATEGORIES = ['general', 'cold_outreach', 'follow_up', 'thank_you', 'meeting_request', 'referral']

export default function Templates() {
  const [search, setSearch] = useState('')
  const [channel, setChannel] = useState('')
  const [category, setCategory] = useState('')

  const params = new URLSearchParams()
  if (channel) params.set('channel', channel)
  if (category) params.set('category', category)
  if (search) params.set('search', search)
  const templatesQ = useQuery<Template[]>({
    queryKey: ['templates', channel, category, search],
    queryFn: () => api.get(`/template-library?${params.toString()}`).then(r => r.data),
  })

  const templates = templatesQ.data || []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Templates"
        eyebrow="Library"
        title="Templates"
        description="Reusable message templates across channels. Bind one to a node, version it, share it."
        actions={
          <>
            <Button variant="secondary" size="md" icon={Sparkles}>Generate with AI</Button>
            <Button variant="primary" size="md" icon={Plus}>New template</Button>
          </>
        }
      />

      <FilterBar>
        <SearchInput placeholder="Search templates…" value={search} onChange={setSearch} />
        <Select value={channel} onChange={setChannel}>
          <option value="">All channels</option>
          {CHANNELS.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
        </Select>
        <Select value={category} onChange={setCategory}>
          <option value="">All categories</option>
          {CATEGORIES.map(c => <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>)}
        </Select>
      </FilterBar>

      {templatesQ.isLoading ? (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {[0,1,2,3,4,5].map(i => <div key={i} className="h-44 skeleton rounded-2xl" />)}
        </div>
      ) : templates.length === 0 ? (
        <Card padding="lg">
          <EmptyState
            icon={FileText}
            title="No templates yet"
            description="Build your first reusable template — bind it to any node in any campaign."
            action={<Button variant="primary" size="sm" icon={Plus}>New template</Button>}
          />
        </Card>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {templates.map(t => <TemplateCard key={t.id} t={t} />)}
        </div>
      )}
    </div>
  )
}

function TemplateCard({ t }: { t: Template }) {
  return (
    <Card padding="md" className="group transition-shadow hover:shadow-sm">
      <div className="flex items-start justify-between">
        <div className="flex min-w-0 items-center gap-2.5">
          <ChannelIcon channel={t.channel} size="md" />
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-white">{t.name}</h3>
            <p className="text-[11px] capitalize text-slate-500">{(t.category || '').replace(/_/g, ' ')}</p>
          </div>
        </div>
        <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
          <Button variant="ghost" size="sm" icon={Copy} />
          <Button variant="ghost" size="sm" icon={Edit2} />
          <Button variant="ghost" size="sm" icon={Trash2} />
        </div>
      </div>
      {t.subject && (
        <div className="mt-3 text-[12px] font-medium text-slate-600 dark:text-slate-300">
          <span className="text-slate-400">Subject </span>{t.subject}
        </div>
      )}
      <p className="mt-1.5 line-clamp-3 text-[13px] leading-relaxed text-slate-500 dark:text-slate-400">{t.body}</p>
      {t.variables && t.variables.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {t.variables.slice(0, 5).map(v => (
            <span key={v} className="rounded-md bg-amber-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-amber-700 dark:bg-amber-900/30 dark:text-amber-300">{`{{${v}}}`}</span>
          ))}
        </div>
      )}
    </Card>
  )
}
