import { FormEvent, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FileText, Plus, Trash2, Pencil, X } from 'lucide-react'
import { templates, type MessageTemplate, type TemplateChannel, type TemplateInput } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import ChannelIcon from '../components/ChannelIcon'
import Select from '../components/Select'
import { useToast } from '../components/Toast'
import { timeAgo } from '../lib/format'

const CHANNELS: TemplateChannel[] = ['email', 'linkedin', 'sms', 'whatsapp', 'instagram', 'telegram', 'voice']

const inputClass =
  'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white'

const EMPTY: TemplateInput = { name: '', channel: 'email', category: '', subject: '', body: '' }

export default function Templates() {
  const qc = useQueryClient()
  const toast = useToast()
  const listQ = useQuery({ queryKey: ['templates'], queryFn: templates.list })
  // null = editor closed; {} draft = creating; populated = editing existing.
  const [editing, setEditing] = useState<{ id?: string; input: TemplateInput } | null>(null)

  const saveMut = useMutation({
    mutationFn: () => {
      const e = editing!
      return e.id ? templates.update(e.id, e.input) : templates.create(e.input)
    },
    onSuccess: () => {
      toast.success(editing?.id ? 'Template updated' : 'Template created')
      setEditing(null)
      qc.invalidateQueries({ queryKey: ['templates'] })
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not save template'),
  })

  const delMut = useMutation({
    mutationFn: templates.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['templates'] }),
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not delete template'),
  })

  const items = listQ.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Templates"
        eyebrow="Setup"
        title="Templates"
        description="Reusable message copy for your campaigns. Supports {{variables}} — paste a template body onto a channel or AI-compose node."
        actions={
          <Button variant="primary" icon={Plus} onClick={() => setEditing({ input: { ...EMPTY } })}>
            New template
          </Button>
        }
      />

      {listQ.isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-24 skeleton rounded-2xl" />)}</div>
      ) : items.length === 0 ? (
        <Card>
          <EmptyState
            icon={FileText}
            title="No templates yet"
            description="Create a reusable template to share message copy across campaigns."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {items.map((t) => (
            <TemplateCard
              key={t.id}
              template={t}
              onEdit={() => setEditing({ id: t.id, input: { name: t.name, channel: t.channel, category: t.category ?? '', subject: t.subject ?? '', body: t.body } })}
              onDelete={() => delMut.mutate(t.id)}
              deleting={delMut.isPending}
            />
          ))}
        </div>
      )}

      {editing && (
        <TemplateEditor
          state={editing}
          onChange={setEditing}
          onCancel={() => setEditing(null)}
          onSave={() => saveMut.mutate()}
          saving={saveMut.isPending}
        />
      )}
    </div>
  )
}

function TemplateCard({
  template,
  onEdit,
  onDelete,
  deleting,
}: {
  template: MessageTemplate
  onEdit: () => void
  onDelete: () => void
  deleting: boolean
}) {
  return (
    <Card padding="md" className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <ChannelIcon channel={template.channel} size="sm" />
          <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{template.name}</span>
          {template.category && <Badge label={template.category} variant="neutral" size="xs" />}
        </div>
        <div className="flex flex-shrink-0 items-center gap-1">
          <button type="button" onClick={onEdit} title="Edit template" aria-label="Edit template" className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800">
            <Pencil size={14} />
          </button>
          <button type="button" onClick={onDelete} disabled={deleting} title="Delete template" aria-label="Delete template" className="rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50 dark:hover:bg-rose-900/20">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {template.subject && <p className="text-xs font-medium text-slate-500">Subject: {template.subject}</p>}
      <p className="line-clamp-3 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">{template.body}</p>
      <p className="mt-auto text-[11px] text-slate-400">Updated {timeAgo(template.updated_at)}</p>
    </Card>
  )
}

function TemplateEditor({
  state,
  onChange,
  onCancel,
  onSave,
  saving,
}: {
  state: { id?: string; input: TemplateInput }
  onChange: (s: { id?: string; input: TemplateInput }) => void
  onCancel: () => void
  onSave: () => void
  saving: boolean
}) {
  const { input } = state
  const set = (patch: Partial<TemplateInput>) => onChange({ ...state, input: { ...input, ...patch } })
  const valid = input.name.trim().length > 0 && input.body.trim().length > 0

  function submit(e: FormEvent) {
    e.preventDefault()
    if (valid) onSave()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onCancel}>
      <Card padding="none" className="w-full max-w-lg" onClick={(e) => e.stopPropagation()}>
        <form onSubmit={submit}>
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3 dark:border-slate-800">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">{state.id ? 'Edit template' : 'New template'}</h2>
            <button type="button" onClick={onCancel} title="Close" aria-label="Close" className="rounded p-1 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">
              <X size={16} />
            </button>
          </div>
          <div className="space-y-3 p-4">
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
                Name
                <input className={`mt-1 ${inputClass}`} value={input.name} onChange={(e) => set({ name: e.target.value })} placeholder="Intro — SaaS founder" autoFocus />
              </label>
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
                Channel
                <Select
                  className="mt-1"
                  ariaLabel="Channel"
                  value={input.channel}
                  onChange={(v) => set({ channel: v as TemplateChannel })}
                  options={CHANNELS.map((c) => ({ value: c, label: c }))}
                />
              </label>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
                Category <span className="text-slate-400">(optional)</span>
                <input className={`mt-1 ${inputClass}`} value={input.category ?? ''} onChange={(e) => set({ category: e.target.value })} placeholder="Cold outreach" />
              </label>
              {input.channel === 'email' && (
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
                  Subject <span className="text-slate-400">(optional)</span>
                  <input className={`mt-1 ${inputClass}`} value={input.subject ?? ''} onChange={(e) => set({ subject: e.target.value })} placeholder="Quick question, {{first_name}}" />
                </label>
              )}
            </div>
            <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
              Body
              <textarea className={`mt-1 ${inputClass} resize-none`} rows={7} value={input.body} onChange={(e) => set({ body: e.target.value })} placeholder="Hi {{first_name}}, I noticed {{company}} is…" />
            </label>
          </div>
          <div className="flex items-center justify-end gap-2 border-t border-slate-100 px-4 py-3 dark:border-slate-800">
            <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={saving}>Cancel</Button>
            <Button type="submit" variant="primary" size="sm" disabled={!valid || saving}>{saving ? 'Saving…' : 'Save template'}</Button>
          </div>
        </form>
      </Card>
    </div>
  )
}
