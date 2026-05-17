import { useState } from 'react'
import { useQuery, useMutation as useRQMutation } from '@tanstack/react-query'
import { Clock, CheckCircle2, X, Check, Edit2, Megaphone, RefreshCw, UserCheck, Save } from 'lucide-react'
import { api } from '../api/client'
import { useToast } from '../components/Toast'
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
  const toast = useToast()
  const [status, setStatus] = useState('pending')
  const [campaignId, setCampaignId] = useState('')

  const campaignsQ = useQuery<Campaign[]>({ queryKey: ['campaigns'], queryFn: () => api.get('/campaigns').then(r => r.data) })
  const approvalsQ = useQuery<{ approvals: Approval[] }>({
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
    onError: () => toast.error('Failed to resolve approval'),
  })

  const editM = useRQMutation({
    mutationFn: ({ id, payload }: { id: string; payload: { body?: string } }) =>
      api.patch(`/approvals/${id}`, { payload }),
    onSuccess: () => { toast.success('Draft updated'); approvalsQ.refetch() },
    onError: () => toast.error('Failed to update draft'),
  })

  const approvals = approvalsQ.data?.approvals || []

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
              onSaveDraft={(body: string) => editM.mutate({ id: a.id, payload: { ...(a.payload || {}), body } })}
              loading={resolveM.isPending}
              saving={editM.isPending}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function ApprovalCard({ a, status, onResolve, onSaveDraft, loading, saving }: { a: Approval; status: string; onResolve: (res: string) => void; onSaveDraft: (body: string) => void; loading: boolean; saving: boolean }) {
  const payloadStr = a.payload && typeof a.payload === 'object' && (a.payload.body || a.payload.message || a.payload.text)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<string>(payloadStr || '')
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
          {(payloadStr || editing) && (
            editing ? (
              <textarea
                value={draft}
                onChange={e => setDraft(e.target.value)}
                rows={5}
                className="mt-2 w-full rounded-xl border border-slate-200 bg-white p-3 text-[13px] leading-relaxed text-slate-700 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-200 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200"
                aria-label="Edit approval draft"
              />
            ) : (
              <div className="mt-2 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-[13px] leading-relaxed text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
                {payloadStr}
              </div>
            )
          )}
          {status === 'pending' && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button variant="primary" size="sm" icon={Check} onClick={() => onResolve('approve')} disabled={loading || editing}>Approve</Button>
              <Button variant="secondary" size="sm" icon={X} onClick={() => onResolve('reject')} disabled={loading || editing}>Reject</Button>
              {editing ? (
                <>
                  <Button variant="primary" size="sm" icon={Save} onClick={() => { onSaveDraft(draft); setEditing(false) }} disabled={saving}>Save</Button>
                  <Button variant="ghost" size="sm" icon={X} onClick={() => { setDraft(payloadStr || ''); setEditing(false) }}>Cancel</Button>
                </>
              ) : (
                <Button variant="ghost" size="sm" icon={Edit2} onClick={() => setEditing(true)}>Edit draft</Button>
              )}
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
