import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive, GitBranch, Megaphone, Plus, RotateCcw, Trash2,
} from 'lucide-react'
import { canvas, integrations, type Workflow } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'
import CampaignArchitect from '../components/CampaignArchitect'

export default function Campaigns() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const { data: campaigns = [], isLoading } = useQuery({ queryKey: ['workflows'], queryFn: canvas.list })
  const { data: templates = [] } = useQuery({ queryKey: ['campaign-templates'], queryFn: canvas.templates })
  const { data: connections = [] } = useQuery({ queryKey: ['integrations'], queryFn: () => integrations.list() })

  const [showCreate, setShowCreate] = useState(false)
  const onCreated = (workflowId: string) => {
    qc.invalidateQueries({ queryKey: ['workflows'] })
    setShowCreate(false)
    navigate(`/campaigns/${workflowId}`)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Campaigns"
        eyebrow="Outreach"
        title="Campaigns"
        description="Multi-step, multi-channel outreach sequences. Each campaign is a graph of nodes."
        actions={
          <Button variant="primary" size="md" icon={Plus} onClick={() => setShowCreate(true)}>
            New campaign
          </Button>
        }
      />

      {showCreate && (
        <CampaignArchitect
          templates={templates}
          connections={connections}
          onCancel={() => setShowCreate(false)}
          onCreated={(detail) => onCreated(detail.workflow.id)}
        />
      )}

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : campaigns.length === 0 ? (
        <Card><EmptyState icon={Megaphone} title="No campaigns yet" description="Create your first campaign and start building a sequence on the canvas." action={<Button variant="primary" size="sm" icon={Plus} onClick={() => setShowCreate(true)}>New campaign</Button>} /></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {campaigns.map((c) => <CampaignCard key={c.id} c={c} />)}
        </div>
      )}
    </div>
  )
}

function CampaignCard({ c }: { c: Workflow }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const tone: 'success' | 'warning' | 'neutral' | 'info' =
    c.status === 'active' ? 'success' : c.status === 'paused' ? 'warning' : c.status === 'archived' ? 'neutral' : 'info'
  const isArchived = c.status === 'archived'

  const invalidate = () => qc.invalidateQueries({ queryKey: ['workflows'] })
  const archiveMut = useMutation({
    mutationFn: () => canvas.archive(c.id),
    onSuccess: () => { invalidate(); toast.success('Campaign archived') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not archive'),
  })
  const unarchiveMut = useMutation({
    mutationFn: () => canvas.update(c.id, { status: 'draft' }),
    onSuccess: () => { invalidate(); toast.success('Campaign restored') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not restore'),
  })
  const deleteMut = useMutation({
    mutationFn: () => canvas.deletePermanent(c.id),
    onSuccess: () => { invalidate(); toast.success('Campaign deleted') },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not delete'),
  })

  // The card body links into the editor; action buttons must NOT navigate.
  const stop = (e: React.MouseEvent) => { e.preventDefault(); e.stopPropagation() }

  return (
    <Link to={`/campaigns/${c.id}`} className="block">
      <Card padding="md" className="transition-shadow hover:shadow-md">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/30">
              <GitBranch size={16} />
            </span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{c.name}</p>
              <p className="mt-0.5 text-[11px] uppercase tracking-[0.12em] text-slate-400">{c.timezone}</p>
            </div>
          </div>
          <Badge label={c.status} variant={tone} dot />
        </div>
        <div className="mt-4 flex items-center justify-between">
          <p className="text-[11px] text-slate-400">Updated {new Date(c.updated_at).toLocaleDateString()}</p>
          <div className="flex items-center gap-1" onClick={stop}>
            {!isArchived ? (
              <Button variant="ghost" size="sm" icon={Archive} isLoading={archiveMut.isPending}
                onClick={(e) => { stop(e); archiveMut.mutate() }} aria-label={`Archive ${c.name}`}>
                Archive
              </Button>
            ) : confirmDelete ? (
              <>
                <Button variant="danger" size="sm" icon={Trash2} isLoading={deleteMut.isPending}
                  onClick={(e) => { stop(e); deleteMut.mutate() }} aria-label={`Confirm delete ${c.name}`}>
                  Delete forever
                </Button>
                <Button variant="ghost" size="sm" onClick={(e) => { stop(e); setConfirmDelete(false) }}>Cancel</Button>
              </>
            ) : (
              <>
                <Button variant="ghost" size="sm" icon={RotateCcw} isLoading={unarchiveMut.isPending}
                  onClick={(e) => { stop(e); unarchiveMut.mutate() }} aria-label={`Restore ${c.name}`}>
                  Restore
                </Button>
                <Button variant="ghost" size="sm" icon={Trash2}
                  onClick={(e) => { stop(e); setConfirmDelete(true) }} aria-label={`Delete ${c.name} permanently`}>
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>
      </Card>
    </Link>
  )
}
