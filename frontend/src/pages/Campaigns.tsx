import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Archive, Building2, ChevronDown, ChevronUp, GitBranch, Megaphone,
  MessageCircle, Plus, Rocket, RotateCcw, Target, Trash2, UserCheck, Users,
} from 'lucide-react'
import { canvas, type ObjectiveMetric, type Workflow } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'

export default function Campaigns() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const { data: campaigns = [], isLoading } = useQuery({ queryKey: ['workflows'], queryFn: canvas.list })
  const { data: templates = [] } = useQuery({ queryKey: ['campaign-templates'], queryFn: canvas.templates })

  const [showCreate, setShowCreate] = useState(false)
  const [name, setName] = useState('')
  const [metric, setMetric] = useState<ObjectiveMetric>('qualified_leads')
  const [target, setTarget] = useState('50')
  const [keywords, setKeywords] = useState('')
  const [location, setLocation] = useState('')
  const [templateId, setTemplateId] = useState<string | null>(null)
  const [showBounds, setShowBounds] = useState(false)
  const [maxIterations, setMaxIterations] = useState('5')
  const [maxSpend, setMaxSpend] = useState('')

  const createGoal = useMutation({
    mutationFn: () => canvas.createFromGoal({
      name: name.trim(),
      metric,
      target: Number(target),
      audience: {
        ...(keywords.trim() ? { keywords: keywords.split(',').map((item) => item.trim()).filter(Boolean) } : {}),
        ...(location.trim() ? { location: location.trim() } : {}),
      },
      bounds: {
        max_iterations: Number(maxIterations) || 5,
        ...(Number(maxSpend) > 0 ? { max_spend_usd: Number(maxSpend) } : {}),
      },
      template_id: templateId,
    }),
    onSuccess: (detail) => {
      qc.invalidateQueries({ queryKey: ['workflows'] })
      setShowCreate(false)
      navigate(`/campaigns/${detail.workflow.id}`)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not create campaign'),
  })
  const targetNumber = Number(target)
  const canCreate = name.trim() && Number.isInteger(targetNumber) && targetNumber > 0

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
        <Card padding="lg" className="space-y-6">
          <div>
            <p className="flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
              <Target size={17} className="text-brand-500" /> What should Omni achieve?
            </p>
            <p className="mt-1 text-xs text-slate-500">
              Start with the outcome. The canvas is the editable plan Omni uses to reach it.
            </p>
          </div>

          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {([
              { value: 'companies', label: 'Find companies', description: 'Build a precise account list', icon: Building2 },
              { value: 'contacts', label: 'Create contacts', description: 'Find the right people', icon: Users },
              { value: 'qualified_leads', label: 'Qualify leads', description: 'Produce sales-ready prospects', icon: UserCheck },
              { value: 'replies', label: 'Earn replies', description: 'Optimize for conversations', icon: MessageCircle },
            ] as const).map((option) => {
              const Icon = option.icon
              const selected = metric === option.value
              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setMetric(option.value)}
                  className={`rounded-xl border p-3 text-left transition-colors ${
                    selected
                      ? 'border-brand-400 bg-brand-50 dark:border-brand-700 dark:bg-brand-950/30'
                      : 'border-slate-200 hover:border-slate-300 dark:border-slate-700'
                  }`}
                >
                  <Icon size={17} className={selected ? 'text-brand-600' : 'text-slate-400'} />
                  <span className="mt-2 block text-sm font-semibold text-slate-900 dark:text-white">{option.label}</span>
                  <span className="mt-0.5 block text-xs text-slate-500">{option.description}</span>
                </button>
              )
            })}
          </div>

          <div className="rounded-2xl bg-slate-50 p-4 dark:bg-slate-800/40">
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Goal sentence</p>
            <div className="mt-3 grid gap-3 md:grid-cols-[140px_1fr_180px]">
              <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                How many?
                <input
                  type="number"
                  min={1}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
                />
              </label>
              <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Who or what are you targeting?
                <input
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  placeholder="B2B SaaS, VP Marketing, Head of Growth"
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
                />
              </label>
              <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                Where?
                <input
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="India or global"
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
                />
              </label>
            </div>
          </div>

          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Starting plan</p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <button
                type="button"
                onClick={() => setTemplateId(null)}
                className={`rounded-xl border p-3 text-left ${templateId === null ? 'border-brand-400 bg-brand-50 dark:bg-brand-950/30' : 'border-slate-200 dark:border-slate-700'}`}
              >
                <GitBranch size={16} className="text-brand-500" />
                <span className="mt-1.5 block text-sm font-semibold text-slate-900 dark:text-white">Design the plan</span>
                <span className="block text-xs text-slate-500">Start with a clean canvas and the goal already attached.</span>
              </button>
              {templates.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  onClick={() => setTemplateId(template.id)}
                  className={`rounded-xl border p-3 text-left ${templateId === template.id ? 'border-brand-400 bg-brand-50 dark:bg-brand-950/30' : 'border-slate-200 dark:border-slate-700'}`}
                >
                  <Rocket size={16} className="text-brand-500" />
                  <span className="mt-1.5 block text-sm font-semibold text-slate-900 dark:text-white">{template.name}</span>
                  <span className="block text-xs text-slate-500">{template.summary}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-xl border border-slate-100 dark:border-slate-800">
            <button
              type="button"
              onClick={() => setShowBounds((value) => !value)}
              className="flex w-full items-center justify-between px-3 py-2.5 text-left"
            >
              <span>
                <span className="block text-xs font-semibold text-slate-700 dark:text-slate-200">Safety bounds</span>
                <span className="block text-[11px] text-slate-400">Stop autonomous pursuit before it overspends or loops.</span>
              </span>
              {showBounds ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
            </button>
            {showBounds && (
              <div className="grid gap-3 border-t border-slate-100 p-3 sm:grid-cols-2 dark:border-slate-800">
                <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  Maximum attempts
                  <input type="number" min={1} value={maxIterations} onChange={(e) => setMaxIterations(e.target.value)}
                    className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900" />
                </label>
                <label className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  Maximum spend (USD)
                  <input type="number" min={0} step="0.5" value={maxSpend} onChange={(e) => setMaxSpend(e.target.value)} placeholder="No cap"
                    className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900" />
                </label>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-4 dark:border-slate-800">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && canCreate && createGoal.mutate()}
              placeholder="Name this campaign"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800"
            />
            <Button variant="primary" icon={Target} onClick={() => createGoal.mutate()} isLoading={createGoal.isPending} disabled={!canCreate}>
              Create goal-driven campaign
            </Button>
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
                  onClick={(e) => { stop(e); setConfirmDelete(true) }} aria-label={`Delete ${c.name}`} />
              </>
            )}
          </div>
        </div>
      </Card>
    </Link>
  )
}
