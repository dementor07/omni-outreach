import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Megaphone, GitBranch } from 'lucide-react'
import { canvas, type Workflow } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'

export default function Campaigns() {
  const qc = useQueryClient()
  const { data: campaigns = [], isLoading } = useQuery({ queryKey: ['workflows'], queryFn: canvas.list })

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const createMut = useMutation({
    mutationFn: () => canvas.create(name.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflows'] })
      setName('')
      setShowCreate(false)
    },
  })

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
        <Card padding="md">
          <div className="flex items-center gap-3">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && name.trim() && createMut.mutate()}
              placeholder="Campaign name (e.g. Q3 SDR outbound)"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800"
            />
            <Button variant="primary" onClick={() => createMut.mutate()} isLoading={createMut.isPending} disabled={!name.trim()}>Create</Button>
            <Button variant="ghost" onClick={() => setShowCreate(false)}>Cancel</Button>
          </div>
        </Card>
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
  const tone: 'success' | 'warning' | 'neutral' | 'info' =
    c.status === 'active' ? 'success' : c.status === 'paused' ? 'warning' : c.status === 'archived' ? 'neutral' : 'info'
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
        <p className="mt-4 text-[11px] text-slate-400">Updated {new Date(c.updated_at).toLocaleDateString()}</p>
      </Card>
    </Link>
  )
}
