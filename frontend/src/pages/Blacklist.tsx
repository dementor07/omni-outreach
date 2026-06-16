import { FormEvent, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ShieldOff, Trash2, Plus, Mail, Globe, Phone, Linkedin } from 'lucide-react'
import { clsx } from 'clsx'
import { suppression, type SuppressionKind, type SuppressionRule } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'

const KIND_META: Record<SuppressionKind, { label: string; icon: typeof Mail; placeholder: string }> = {
  email: { label: 'Email', icon: Mail, placeholder: 'person@example.com' },
  domain: { label: 'Domain', icon: Globe, placeholder: 'competitor.com' },
  phone: { label: 'Phone', icon: Phone, placeholder: '+1 555 010 0000' },
  linkedin: { label: 'LinkedIn', icon: Linkedin, placeholder: 'linkedin.com/in/handle' },
}

const inputClass =
  'rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white'

export default function Blacklist() {
  const qc = useQueryClient()
  const toast = useToast()
  const rulesQ = useQuery({ queryKey: ['suppression'], queryFn: suppression.list })

  const [kind, setKind] = useState<SuppressionKind>('email')
  const [value, setValue] = useState('')
  const [reason, setReason] = useState('')

  const addMut = useMutation({
    mutationFn: () => suppression.create(kind, value.trim(), reason.trim() || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['suppression'] })
      setValue(''); setReason('')
      toast.success('Suppression rule added')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not add rule'),
  })
  const delMut = useMutation({
    mutationFn: suppression.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['suppression'] }),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (value.trim()) addMut.mutate()
  }

  const rules = rulesQ.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Blacklist"
        eyebrow="Setup"
        title="Blacklist"
        description="Domains and addresses to suppress across every campaign — unsubscribes, competitors, do-not-contact. Enforced at send: a suppressed contact is never messaged on any channel."
      />

      <Card className="p-4">
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
            Type
            <select aria-label="Suppression type" value={kind} onChange={(e) => setKind(e.target.value as SuppressionKind)} className={inputClass}>
              {(Object.keys(KIND_META) as SuppressionKind[]).map((k) => (
                <option key={k} value={k}>{KIND_META[k].label}</option>
              ))}
            </select>
          </label>
          <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-xs font-medium text-slate-500">
            Value
            <input aria-label="Value to suppress" value={value} onChange={(e) => setValue(e.target.value)} placeholder={KIND_META[kind].placeholder} className={inputClass} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
            Reason <span className="text-slate-400">(optional)</span>
            <input aria-label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="unsubscribed" className={inputClass} />
          </label>
          <Button type="submit" variant="primary" icon={Plus} isLoading={addMut.isPending} disabled={!value.trim()}>Add rule</Button>
        </form>
      </Card>

      <Card padding={rules.length === 0 ? 'lg' : 'none'}>
        {rulesQ.isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading…</p>
        ) : rules.length === 0 ? (
          <EmptyState
            icon={ShieldOff}
            title="No suppression rules yet"
            description="Add an email, domain, phone, or LinkedIn handle above. Unsubscribe replies are auto-suppressed via the inbox classifier."
          />
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-800">
            {rules.map((r: SuppressionRule) => {
              const meta = KIND_META[r.kind as SuppressionKind] ?? KIND_META.email
              const Icon = meta.icon
              return (
                <div key={r.id} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500 dark:bg-slate-800">
                    <Icon size={15} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{r.value}</p>
                    {r.reason && <p className="truncate text-xs text-slate-400">{r.reason}</p>}
                  </div>
                  <Badge label={r.source} variant={r.source === 'unsubscribe' ? 'warning' : 'neutral'} size="xs" />
                  <button
                    type="button"
                    aria-label={`Remove ${r.value}`}
                    onClick={() => delMut.mutate(r.id)}
                    className={clsx('rounded-lg p-2 text-slate-300 transition-colors hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-900/20', delMut.isPending && 'opacity-50')}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
