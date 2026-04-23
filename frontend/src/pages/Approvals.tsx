import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, XCircle, Loader2, UserCheck, Inbox as InboxIcon } from 'lucide-react'
import { clsx } from 'clsx'

import { api } from '../api/client'
import { useToast } from '../components/Toast'

interface Approval {
  id: string
  campaign_id: string
  campaign_name: string
  lead_id: string
  node_id: string
  title: string
  payload: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected'
  resolution: string | null
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
  first_name: string | null
  last_name: string | null
  email: string | null
  linkedin_url: string | null
  headline: string | null
  company: string | null
}

type StatusFilter = 'pending' | 'approved' | 'rejected'

export default function Approvals() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending')
  const [note, setNote] = useState<Record<string, string>>({})
  const [busyId, setBusyId] = useState<string | null>(null)

  const { data: approvals, isLoading } = useQuery<Approval[]>({
    queryKey: ['approvals', statusFilter],
    queryFn: () => api.get<Approval[]>(`/approvals?status=${statusFilter}&limit=100`).then(r => r.data),
    refetchInterval: statusFilter === 'pending' ? 15_000 : false,
  })

  const resolveMutation = useMutation({
    mutationFn: async ({ id, resolution }: { id: string; resolution: 'approve' | 'reject' }) =>
      (await api.post(`/approvals/${id}/resolve`, { resolution, note: note[id] || null })).data,
    onSuccess: (_, variables) => {
      setBusyId(null)
      toast.success(variables.resolution === 'approve' ? 'Approved' : 'Rejected')
      void queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
    onError: () => {
      setBusyId(null)
      toast.error('Failed to resolve approval')
    },
  })

  function resolve(id: string, resolution: 'approve' | 'reject') {
    setBusyId(id)
    resolveMutation.mutate({ id, resolution })
  }

  const rows = approvals || []

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Approvals</h1>
          <p className="text-sm text-slate-500 mt-0.5">
            Review leads parked at <code>human_approval</code> nodes. Decisions unpark the sequence.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
          {(['pending', 'approved', 'rejected'] as StatusFilter[]).map(s => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={clsx(
                'px-3 py-1.5 rounded-md text-xs font-semibold capitalize transition-colors',
                statusFilter === s ? 'bg-sky-500 text-white' : 'text-slate-500 hover:bg-slate-50',
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 size={24} className="animate-spin text-slate-400" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-64 text-slate-400">
          <InboxIcon size={40} className="mb-3 opacity-40" />
          <p className="text-sm">No {statusFilter} approvals</p>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map(a => (
            <ApprovalCard
              key={a.id}
              approval={a}
              note={note[a.id] || ''}
              onNoteChange={(v) => setNote(n => ({ ...n, [a.id]: v }))}
              onResolve={resolve}
              busy={busyId === a.id}
              editable={statusFilter === 'pending'}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface ApprovalCardProps {
  approval: Approval
  note: string
  onNoteChange: (v: string) => void
  onResolve: (id: string, resolution: 'approve' | 'reject') => void
  busy: boolean
  editable: boolean
}

function ApprovalCard({ approval, note, onNoteChange, onResolve, busy, editable }: ApprovalCardProps) {
  const leadName = [approval.first_name, approval.last_name].filter(Boolean).join(' ') || '—'
  const payloadPretty = (() => {
    try { return JSON.stringify(approval.payload, null, 2) } catch { return String(approval.payload) }
  })()

  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      <div className="flex items-start gap-3 px-5 py-4 border-b border-slate-100">
        <div className="flex items-center justify-center w-9 h-9 rounded-lg flex-shrink-0 bg-teal-50 text-teal-600">
          <UserCheck size={15} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-slate-900">{approval.title}</span>
            {approval.status !== 'pending' && (
              <span className={clsx(
                'text-[10px] uppercase font-bold px-2 py-0.5 rounded',
                approval.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700',
              )}>{approval.status}</span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            {leadName}{approval.company ? ` · ${approval.company}` : ''}{approval.headline ? ` · ${approval.headline}` : ''}
          </p>
          <p className="text-[11px] text-slate-400 mt-0.5">
            Campaign <span className="font-medium">{approval.campaign_name}</span>
            {' · '}
            Created {new Date(approval.created_at).toLocaleString()}
            {approval.resolved_at && ` · Resolved ${new Date(approval.resolved_at).toLocaleString()}${approval.resolved_by ? ` by ${approval.resolved_by}` : ''}`}
          </p>
        </div>
      </div>

      {payloadPretty && payloadPretty !== '{}' && (
        <div className="px-5 py-3 bg-slate-50/60">
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1">Preview</p>
          <pre className="text-[11px] text-slate-700 font-mono whitespace-pre-wrap break-words max-h-64 overflow-auto">{payloadPretty}</pre>
        </div>
      )}

      {editable && (
        <div className="px-5 py-3 flex items-center gap-3">
          <input
            type="text"
            value={note}
            onChange={(e) => onNoteChange(e.target.value)}
            placeholder="Note (optional — shown in resolution history)"
            className="flex-1 rounded-lg border border-slate-200 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-sky-500"
          />
          <button
            type="button"
            onClick={() => onResolve(approval.id, 'reject')}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-rose-50 text-rose-700 hover:bg-rose-100 disabled:opacity-50"
          >
            <XCircle size={13} /> Reject
          </button>
          <button
            type="button"
            onClick={() => onResolve(approval.id, 'approve')}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
          >
            <CheckCircle2 size={13} /> Approve
          </button>
        </div>
      )}
    </div>
  )
}
