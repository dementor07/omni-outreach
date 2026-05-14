import { useState } from 'react'
import { useQuery, useMutation as useRQMutation } from '@tanstack/react-query'
import { Clock, CheckCircle2, X, Check, Edit2, Megaphone, RefreshCw, UserCheck } from 'lucide-react'
import { api } from '../api/client'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import Avatar from '../components/Avatar'
import { FilterBar, SearchInput, Select, Toggle } from '../components/FilterBar'
import { fullName, timeAgo } from '../lib/format'

interface Approval { id: string; first_name?: string; last_name?: string; headline?: string; campaign_name?: string; title?: string; payload?: { body?: string; message?: string; text?: string }; status: string; created_at: string; resolved_at?: string; resolution?: string }
interface Campaign { id: string; name: string }

export default function Approvals() {
  const [status, setStatus] = useState('pending')
  const [campaignId, setCampaignId] = useState('')

  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const approvalsQ = useQuery<Approval[]>({
    queryKey: ['approvals', status, campaignId],
    queryFn: () => {
      const params = new URLSearchParams()
      if (status) params.set('status', status)
      if (campaignId) params.set('campaign_id', campaignId)
      params.set('limit', '100')
      return api.get(`/approvals?${params.toString()}`).then(r => r.data)
    },
  })

  const resolveM = useRQMutation({
    mutationFn: ({ id, resolution }: { id: string; resolution: string }) =>
      api.post(`/approvals/${id}/resolve`, { resolution }),
    onSuccess: () => approvalsQ.refetch(),
  })

  const approvals = approvalsQ.data || []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Approvals"
        eyebrow="Human-in-the-loop"
        title="Approvals"
        description="Review drafts and decisions parked by human-approval nodes. Approve to advance, reject to branch."
        actions={<Button variant="secondary" size="md" icon={RefreshCw} onClick={() => approvalsQ.refetch()}>Refresh</Button>}
      />

      <FilterBar>
        <SearchInput placeholder="Search by lead, title, payload…" value="" onChange={() => {}} />
        <Select value={campaignId} onChange={setCampaignId}>
          <option value="">All campaigns</option>
          {(campaignsQ.data || []).map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
        <Toggle
          value={status}
          onChange={setStatus}
          items={[
            { value: 'pending', label: 'Pending', icon: Clock },
            { value: 'approved', label: 'Approved', icon: CheckCircle2 },
            { value: 'rejected', label: 'Rejected', icon: X },
          ]}
        />
      </FilterBar>

      {approvalsQ.isLoading ? (
        <div className="space-y-2">{[0,1,2].map(i => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : approvals.length === 0 ? (
        <Card padding="lg">
          <EmptyState
            icon={UserCheck}
            title={`No ${status} approvals`}
            description={status === 'pending' ? 'When a human-approval node parks a lead, it shows up here.' : 'Switch tabs to see resolved approvals.'}
          />
        </Card>
      ) : (
        <div className="space-y-3">
          {approvals.map(a => (
            <ApprovalCard
              key={a.id}
              a={a}
              status={status}
              onResolve={(resolution: string) => resolveM.mutate({ id: a.id, resolution })}
              loading={resolveM.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ApprovalCard({ a, status, onResolve, loading }: { a: Approval; status: string; onResolve: (res: string) => void; loading: boolean }) {
  const payloadStr = a.payload && typeof a.payload === 'object' && (a.payload.body || a.payload.message || a.payload.text)
  return (
    <Card padding="md">
      <div className="flex items-start gap-3">
        <Avatar name={fullName(a)} size={40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="truncate text-sm font-semibold text-slate-900 dark:text-white">{fullName(a)}</span>
                {a.headline && <span className="truncate text-[12px] text-slate-500">· {a.headline}</span>}
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500">
                <Megaphone size={11} />
                <span className="truncate">{a.campaign_name || 'Campaign'}</span>
                <span className="text-slate-300">·</span>
                <span>{timeAgo(a.created_at)}</span>
              </div>
            </div>
            <Badge label={status} asStatus dot />
          </div>
          {a.title && <p className="mt-3 text-[13px] font-medium text-slate-700 dark:text-slate-200">{a.title}</p>}
          {payloadStr && (
            <div className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-[13px] leading-relaxed text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              {payloadStr}
            </div>
          )}
          {status === 'pending' && (
            <div className="mt-3 flex items-center gap-2">
              <Button variant="primary" size="sm" icon={Check} onClick={() => onResolve('approve')} disabled={loading}>Approve</Button>
              <Button variant="secondary" size="sm" icon={X} onClick={() => onResolve('reject')} disabled={loading}>Reject</Button>
              <Button variant="ghost" size="sm" icon={Edit2}>Edit draft</Button>
            </div>
          )}
          {status !== 'pending' && a.resolved_at && (
            <p className="mt-3 text-[11px] text-slate-500">
              Resolved {timeAgo(a.resolved_at)}
              {a.resolution && <> · {a.resolution}</>}
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}
