import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserCheck, Check, X, Clock, Sparkles, Save } from 'lucide-react'
import { approvals, type Approval } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'
import { timeAgo } from '../lib/format'

export default function Approvals() {
  const { data: pending = [], isLoading } = useQuery({
    queryKey: ['approvals'],
    queryFn: approvals.list,
  })

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Approvals"
        eyebrow="Human-in-the-loop"
        title="Approvals"
        description="Drafts and decisions parked by human-approval nodes. Review the AI draft, then approve to advance or reject to branch."
      />

      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : pending.length === 0 ? (
        <Card><EmptyState icon={UserCheck} title="No pending approvals" description="When a human-approval node parks a lead, it shows up here." /></Card>
      ) : (
        <div className="space-y-3">
          {pending.map((a) => <ApprovalCard key={a.id} approval={a} />)}
        </div>
      )}
    </div>
  )
}

function ApprovalCard({ approval }: { approval: Approval }) {
  const qc = useQueryClient()
  const toast = useToast()
  // null = not editing; otherwise the working draft text.
  const [editing, setEditing] = useState<string | null>(null)

  const invalidate = () => qc.invalidateQueries({ queryKey: ['approvals'] })

  const saveMut = useMutation({
    mutationFn: () => approvals.updateDraft(approval.id, editing ?? ''),
    onSuccess: () => {
      toast.success('Draft updated')
      setEditing(null)
      setTimeout(invalidate, 400)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not save draft'),
  })

  const resolveMut = useMutation({
    mutationFn: (handle: 'approved' | 'rejected') => approvals.resolve(approval.id, handle),
    onSuccess: (_res, handle) => {
      toast.success(handle === 'approved' ? 'Approved — lead advancing' : 'Rejected — lead branching')
      setTimeout(invalidate, 400)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not resolve'),
  })

  const busy = saveMut.isPending || resolveMut.isPending

  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <Clock size={11} />
            <span>{timeAgo(approval.created_at)}</span>
            <span className="text-slate-300">·</span>
            <span>lead {approval.lead_id.slice(0, 8)}</span>
          </div>
          <p className="mt-2 text-[13px] font-medium text-slate-700 dark:text-slate-200">{approval.prompt || 'Approval requested'}</p>
        </div>
        <Badge label="pending" variant="warning" dot />
      </div>

      {/* AI draft-review (B1): present when an upstream ai.compose populated it. */}
      {(approval.draft !== null || editing !== null) && (
        <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50/50 p-3 dark:border-violet-900/40 dark:bg-violet-900/10">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-violet-700 dark:text-violet-300">
            <Sparkles size={12} />
            AI draft — review before approving
          </div>
          {editing !== null ? (
            <textarea
              value={editing}
              onChange={(e) => setEditing(e.target.value)}
              rows={4}
              aria-label="AI draft"
              placeholder="Edit the AI-composed draft…"
              className="w-full resize-none rounded-md border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-900 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40"
            />
          ) : (
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700 dark:text-slate-200">{approval.draft}</p>
          )}
          <div className="mt-2 flex items-center gap-2">
            {editing !== null ? (
              <>
                <Button variant="primary" size="sm" icon={Save} onClick={() => saveMut.mutate()} disabled={busy}>Save draft</Button>
                <Button variant="ghost" size="sm" onClick={() => setEditing(null)} disabled={busy}>Cancel</Button>
              </>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => setEditing(approval.draft ?? '')} disabled={busy}>Edit draft</Button>
            )}
          </div>
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button variant="primary" size="sm" icon={Check} onClick={() => resolveMut.mutate('approved')} disabled={busy || editing !== null}>Approve</Button>
        <Button variant="secondary" size="sm" icon={X} onClick={() => resolveMut.mutate('rejected')} disabled={busy || editing !== null}>Reject</Button>
      </div>
    </Card>
  )
}
