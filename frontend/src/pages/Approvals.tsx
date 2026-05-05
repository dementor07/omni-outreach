import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, XCircle, Loader2, UserCheck, Inbox as InboxIcon, Pencil, Save, X } from 'lucide-react'
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
  payload: Record<string, any>
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

  const updateMutation = useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: any }) =>
      (await api.patch(`/approvals/${id}`, { payload })).data,
    onSuccess: () => {
      toast.success('Draft updated')
      void queryClient.invalidateQueries({ queryKey: ['approvals'] })
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Failed to update draft')
    },
  })

  function resolve(id: string, resolution: 'approve' | 'reject') {
    setBusyId(id)
    resolveMutation.mutate({ id, resolution })
  }

  const rows = approvals || []

  return (
    <div className="max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">Approvals</h1>
          <p className="text-sm text-slate-500 mt-1">
            Review and edit AI-generated drafts before they reach the lead.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-2xl border border-slate-200 bg-white p-1 shadow-sm">
          {(['pending', 'approved', 'rejected'] as StatusFilter[]).map(s => (
            <button
              key={s}
              type="button"
              onClick={() => setStatusFilter(s)}
              className={clsx(
                'px-4 py-2 rounded-xl text-xs font-bold capitalize transition-all',
                statusFilter === s ? 'bg-sky-500 text-white shadow-md shadow-sky-100' : 'text-slate-500 hover:bg-slate-50',
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 size={32} className="animate-spin text-sky-400" />
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 rounded-3xl border-2 border-dashed border-slate-200 bg-slate-50/50 text-slate-400">
          <InboxIcon size={48} className="mb-4 opacity-20" />
          <p className="text-sm font-medium uppercase tracking-widest">No {statusFilter} approvals</p>
        </div>
      ) : (
        <div className="space-y-6">
          {rows.map(a => (
            <ApprovalCard
              key={a.id}
              approval={a}
              note={note[a.id] || ''}
              onNoteChange={(v) => setNote(n => ({ ...n, [a.id]: v }))}
              onResolve={resolve}
              onUpdate={(payload) => updateMutation.mutate({ id: a.id, payload })}
              busy={busyId === a.id || updateMutation.isPending}
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
  onUpdate: (payload: any) => void
  busy: boolean
  editable: boolean
}

function ApprovalCard({ approval, note, onNoteChange, onResolve, onUpdate, busy, editable }: ApprovalCardProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [editedPayload, setEditedPayload] = useState(JSON.stringify(approval.payload, null, 2))

  const leadName = [approval.first_name, approval.last_name].filter(Boolean).join(' ') || '—'

  const handleSave = () => {
    try {
      const parsed = JSON.parse(editedPayload)
      onUpdate(parsed)
      setIsEditing(false)
    } catch {
      alert('Invalid JSON format')
    }
  }

  return (
    <div className="group relative rounded-3xl border border-slate-200 bg-white shadow-sm transition-all hover:shadow-md overflow-hidden">
      <div className="flex items-start gap-4 px-6 py-6 border-b border-slate-50">
        <div className="flex items-center justify-center w-12 h-12 rounded-2xl flex-shrink-0 bg-sky-50 text-sky-600">
          <UserCheck size={20} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-base font-bold text-slate-900">{approval.title}</span>
            {approval.status !== 'pending' && (
              <span className={clsx(
                'text-[10px] uppercase font-black tracking-widest px-2.5 py-1 rounded-lg',
                approval.status === 'approved' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700',
              )}>{approval.status}</span>
            )}
          </div>
          <p className="text-sm text-slate-600 mt-1">
            <span className="font-semibold text-slate-900">{leadName}</span>
            {approval.company && <span className="text-slate-400"> · {approval.company}</span>}
            {approval.headline && <span className="text-slate-400 italic"> · {approval.headline}</span>}
          </p>
          <div className="flex items-center gap-2 mt-3 text-[11px] text-slate-400">
            <span className="font-black uppercase tracking-tighter text-slate-300">Campaign</span>
            <span className="bg-slate-100 px-2 py-0.5 rounded text-slate-600">{approval.campaign_name}</span>
            <span className="mx-1 opacity-50">/</span>
            <span>{new Date(approval.created_at).toLocaleString()}</span>
          </div>
        </div>
        
        {editable && !isEditing && (
          <button 
            onClick={() => setIsEditing(true)}
            className="p-2 rounded-xl text-slate-400 hover:text-sky-600 hover:bg-sky-50 transition-all"
            title="Edit Draft"
          >
            <Pencil size={16} />
          </button>
        )}
      </div>

      <div className="relative">
        {isEditing ? (
          <div className="p-4 bg-slate-900">
            <textarea
              value={editedPayload}
              onChange={(e) => setEditedPayload(e.target.value)}
              className="w-full h-64 bg-transparent text-emerald-400 font-mono text-xs outline-none resize-none"
              spellCheck={false}
            />
            <div className="flex justify-end gap-2 mt-2">
              <button
                onClick={() => { setIsEditing(false); setEditedPayload(JSON.stringify(approval.payload, null, 2)) }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-bold text-slate-400 hover:text-white transition-colors"
              >
                <X size={12} /> Cancel
              </button>
              <button
                onClick={handleSave}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-[11px] font-bold bg-sky-600 text-white hover:bg-sky-500 transition-colors shadow-lg shadow-sky-900/20"
              >
                <Save size={12} /> Save Changes
              </button>
            </div>
          </div>
        ) : (
          approval.payload && JSON.stringify(approval.payload) !== '{}' && (
            <div className="px-6 py-4 bg-slate-50/50">
              <p className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2">Message Draft</p>
              <pre className="text-xs text-slate-700 font-mono whitespace-pre-wrap break-words max-h-64 overflow-auto scrollbar-hide">
                {typeof approval.payload === 'object' && 'body' in approval.payload 
                  ? String(approval.payload.body) 
                  : JSON.stringify(approval.payload, null, 2)}
              </pre>
            </div>
          )
        )}
      </div>

      {editable && (
        <div className="px-6 py-4 bg-white flex items-center gap-4">
          <input
            type="text"
            value={note}
            onChange={(e) => onNoteChange(e.target.value)}
            placeholder="Add internal note..."
            className="flex-1 bg-slate-50 rounded-2xl border-none px-4 py-2.5 text-sm placeholder:text-slate-400 focus:ring-2 focus:ring-sky-500 transition-all"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onResolve(approval.id, 'reject')}
              disabled={busy || isEditing}
              className="flex items-center gap-2 px-5 py-2.5 rounded-2xl text-sm font-bold text-rose-600 hover:bg-rose-50 transition-all disabled:opacity-30"
            >
              <XCircle size={16} /> Reject
            </button>
            <button
              type="button"
              onClick={() => onResolve(approval.id, 'approve')}
              disabled={busy || isEditing}
              className="flex items-center gap-2 px-6 py-2.5 rounded-2xl text-sm font-bold bg-sky-600 text-white hover:bg-sky-700 transition-all shadow-lg shadow-sky-100 disabled:opacity-30"
            >
              <CheckCircle2 size={16} /> Approve
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
