import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserCheck, Check, X, Clock } from 'lucide-react'
import { events, type OmniEvent } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { timeAgo } from '../lib/format'

export default function Approvals() {
  const qc = useQueryClient()
  const { data: requested = [], isLoading } = useQuery({
    queryKey: ['approvals'],
    queryFn: () => events.list({ event_type: 'approval.requested', limit: 100 }),
  })

  const resolveMut = useMutation({
    mutationFn: ({ ev, decision }: { ev: OmniEvent; decision: 'approved' | 'rejected' }) =>
      events.publish({
        event_type: 'approval.resolved',
        entity_type: 'lead',
        entity_id: ev.entity_id ?? undefined,
        payload: { decision, correlation_id: ev.correlation_id },
        correlation_id: ev.correlation_id ?? undefined,
      }),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['approvals'] }), 500),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Approvals"
        eyebrow="Human-in-the-loop"
        title="Approvals"
        description="Drafts and decisions parked by human-approval nodes. Approve to advance, reject to branch."
      />

      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : requested.length === 0 ? (
        <Card><EmptyState icon={UserCheck} title="No pending approvals" description="When a human-approval node parks a lead, it shows up here." /></Card>
      ) : (
        <div className="space-y-3">
          {requested.map((ev) => (
            <Card key={ev.id} padding="md">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <Clock size={11} />
                    <span>{timeAgo(ev.occurred_at)}</span>
                    {ev.entity_id && <><span className="text-slate-300">·</span><span>lead {ev.entity_id.slice(0, 8)}</span></>}
                  </div>
                  <p className="mt-2 text-[13px] font-medium text-slate-700 dark:text-slate-200">
                    {(ev.payload.prompt as string) ?? 'Approval requested'}
                  </p>
                </div>
                <Badge label="pending" variant="warning" dot />
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Button variant="primary" size="sm" icon={Check} onClick={() => resolveMut.mutate({ ev, decision: 'approved' })} disabled={resolveMut.isPending}>Approve</Button>
                <Button variant="secondary" size="sm" icon={X} onClick={() => resolveMut.mutate({ ev, decision: 'rejected' })} disabled={resolveMut.isPending}>Reject</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
