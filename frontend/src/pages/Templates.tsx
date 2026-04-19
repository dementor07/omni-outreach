import { useState } from 'react'
import { FileText, Plus, Search, Trash2, Edit2, X, Copy, Mail, Linkedin, MessageSquare, Phone } from 'lucide-react'
import { useTemplateLibrary, useCreateLibraryTemplate, useDeleteLibraryTemplate, type LibraryTemplate } from '../hooks/useTemplateLibrary'
import { useToast } from '../components/Toast'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'

const CHANNELS = [
  { key: 'email', label: 'Email', icon: Mail },
  { key: 'linkedin_dm', label: 'LinkedIn DM', icon: Linkedin },
  { key: 'linkedin_inmail', label: 'InMail', icon: Linkedin },
  { key: 'whatsapp', label: 'WhatsApp', icon: MessageSquare },
  { key: 'sms', label: 'SMS', icon: Phone },
]

const CATEGORIES = ['general', 'cold_outreach', 'follow_up', 'thank_you', 'meeting_request', 'referral']

export default function Templates() {
  const [channelFilter, setChannelFilter] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [previewTemplate, setPreviewTemplate] = useState<LibraryTemplate | null>(null)
  const [form, setForm] = useState({ name: '', channel: 'email', category: 'general', subject: '', body: '' })

  const { data: templates, isLoading } = useTemplateLibrary(channelFilter || undefined, categoryFilter || undefined, search || undefined)
  const createTemplate = useCreateLibraryTemplate()
  const deleteTemplate = useDeleteLibraryTemplate()
  const toast = useToast()

  const handleCreate = async () => {
    if (!form.name.trim() || !form.body.trim()) return
    await createTemplate.mutateAsync(form)
    toast.success('Template created')
    setCreateOpen(false)
    setForm({ name: '', channel: 'email', category: 'general', subject: '', body: '' })
  }

  const handleDelete = async (id: string) => {
    await deleteTemplate.mutateAsync(id)
    toast.success('Template deleted')
  }

  const handleCopy = (template: LibraryTemplate) => {
    navigator.clipboard.writeText(template.body)
    toast.success('Copied to clipboard')
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-slate-900">Template Library</h1>
          <p className="mt-1 text-sm text-slate-500">Reusable message templates across all channels</p>
        </div>
        <button
          onClick={() => setCreateOpen(true)}
          className="flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-600"
        >
          <Plus size={16} /> New Template
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
          <Search size={14} className="text-slate-400" />
          <input
            type="text"
            placeholder="Search templates..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full text-sm text-slate-700 outline-none placeholder:text-slate-400"
          />
          {search && <button onClick={() => setSearch('')} className="text-slate-400 hover:text-slate-600"><X size={14} /></button>}
        </div>
        <select
          value={channelFilter}
          onChange={(e) => setChannelFilter(e.target.value)}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none"
        >
          <option value="">All channels</option>
          {CHANNELS.map((ch) => <option key={ch.key} value={ch.key}>{ch.label}</option>)}
        </select>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm outline-none"
        >
          <option value="">All categories</option>
          {CATEGORIES.map((cat) => <option key={cat} value={cat}>{cat.replace(/_/g, ' ')}</option>)}
        </select>
      </div>

      {/* Template grid */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => <div key={i} className="h-48 animate-pulse rounded-2xl bg-slate-100" />)}
        </div>
      ) : !templates?.length ? (
        <EmptyState icon={FileText} title="No templates yet" description="Create your first reusable template to use across campaigns." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {templates.map((t) => {
            const channelCfg = CHANNELS.find((ch) => ch.key === t.channel)
            const Icon = channelCfg?.icon || FileText
            return (
              <div key={t.id} className="group rounded-2xl border border-slate-200 bg-white p-5 transition-shadow hover:shadow-md">
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-2">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-sky-100 text-sky-600">
                      <Icon size={14} />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900">{t.name}</h3>
                      <span className="text-xs capitalize text-slate-400">{t.category.replace(/_/g, ' ')}</span>
                    </div>
                  </div>
                  <div className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    <button onClick={() => handleCopy(t)} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Copy"><Copy size={13} /></button>
                    <button onClick={() => handleDelete(t.id)} className="rounded-lg p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-500" title="Delete"><Trash2 size={13} /></button>
                  </div>
                </div>
                {t.subject && <div className="mt-3 text-xs font-medium text-slate-500">Subject: {t.subject}</div>}
                <p className="mt-2 line-clamp-3 text-xs text-slate-600 leading-relaxed">{t.body}</p>
                {t.variables.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1">
                    {t.variables.map((v) => (
                      <span key={v} className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-600">
                        {`{{${v}}}`}
                      </span>
                    ))}
                  </div>
                )}
                <button
                  onClick={() => setPreviewTemplate(t)}
                  className="mt-3 text-xs font-medium text-sky-500 hover:text-sky-600"
                >
                  Preview
                </button>
              </div>
            )
          })}
        </div>
      )}

      {/* Create modal */}
      <Modal title="Create Template" open={createOpen} onClose={() => setCreateOpen(false)} width="lg">
        <div className="space-y-4">
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Template Name</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g., Cold Outreach — First Touch"
              className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:border-sky-300"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">Channel</label>
              <select
                value={form.channel}
                onChange={(e) => setForm({ ...form, channel: e.target.value })}
                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none"
              >
                {CHANNELS.map((ch) => <option key={ch.key} value={ch.key}>{ch.label}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">Category</label>
              <select
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-sm outline-none"
              >
                {CATEGORIES.map((cat) => <option key={cat} value={cat}>{cat.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
          </div>
          {form.channel === 'email' && (
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-500">Subject</label>
              <input
                type="text"
                value={form.subject}
                onChange={(e) => setForm({ ...form, subject: e.target.value })}
                placeholder="Use {{first_name}} for personalization"
                className="w-full rounded-xl border border-slate-200 px-4 py-2.5 text-sm outline-none focus:border-sky-300"
              />
            </div>
          )}
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-500">Body</label>
            <textarea
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
              rows={8}
              placeholder="Hi {{first_name}}, I noticed your work at {{company}}..."
              className="w-full rounded-xl border border-slate-200 px-4 py-3 text-sm outline-none focus:border-sky-300"
            />
            <p className="mt-1 text-xs text-slate-400">Use {'{{variable}}'} for dynamic fields</p>
          </div>
          <button
            onClick={handleCreate}
            disabled={!form.name.trim() || !form.body.trim() || createTemplate.isPending}
            className="w-full rounded-xl bg-sky-500 py-2.5 text-sm font-semibold text-white hover:bg-sky-600 disabled:opacity-40"
          >
            {createTemplate.isPending ? 'Creating...' : 'Create Template'}
          </button>
        </div>
      </Modal>

      {/* Preview modal */}
      <Modal title={previewTemplate?.name || 'Preview'} open={!!previewTemplate} onClose={() => setPreviewTemplate(null)} width="lg">
        {previewTemplate && (
          <div className="space-y-4">
            <div className="flex gap-2">
              <span className="rounded-full bg-sky-100 px-2.5 py-1 text-xs font-medium text-sky-700">{previewTemplate.channel}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 capitalize">{previewTemplate.category.replace(/_/g, ' ')}</span>
            </div>
            {previewTemplate.subject && (
              <div>
                <div className="text-xs font-medium text-slate-400">Subject</div>
                <div className="mt-1 text-sm text-slate-700">{previewTemplate.subject}</div>
              </div>
            )}
            <div>
              <div className="text-xs font-medium text-slate-400">Body</div>
              <div className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-4 text-sm text-slate-700 leading-relaxed">
                {previewTemplate.body}
              </div>
            </div>
            {previewTemplate.variables.length > 0 && (
              <div>
                <div className="text-xs font-medium text-slate-400">Variables</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {previewTemplate.variables.map((v) => (
                    <span key={v} className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-medium text-amber-600">{`{{${v}}}`}</span>
                  ))}
                </div>
              </div>
            )}
            <button
              onClick={() => { handleCopy(previewTemplate); setPreviewTemplate(null) }}
              className="flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-2.5 text-sm font-semibold text-white hover:bg-sky-600"
            >
              <Copy size={14} /> Copy to clipboard
            </button>
          </div>
        )}
      </Modal>
    </div>
  )
}
