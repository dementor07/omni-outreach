import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Users, Contact as ContactIcon, KanbanSquare, Inbox as InboxIcon,
  Megaphone, Sparkles, Plus, TrendingUp, Flame, Copy, Pencil, Trash2, AlertTriangle,
} from 'lucide-react'
import { clsx } from 'clsx'
import { projections, inbox, canvas, ai, views, type Deal, type LeadScore, type ViewDef } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card, { CardHeader } from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Modal from '../components/Modal'
import EmptyState from '../components/EmptyState'
import ComposableView from '../components/ComposableView'
import { useToast } from '../components/Toast'

const DEAL_STAGE_ORDER = ['lead', 'qualified', 'meeting', 'proposal', 'closed_won', 'closed_lost']

/** Surface the API's own message (e.g. a 422 detail) instead of a generic one. */
function viewError(error: unknown, fallback: string): string {
  return (
    (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    (error instanceof Error ? error.message : fallback)
  )
}

/**
 * DYNAMIC-002 step 1: the home page is a stored view (data), not this hardcoded
 * React. We load the workspace's default Overview view and render it through the
 * generic widget renderer. If that fails for ANY reason (endpoint down, seed
 * error, old backend), we fall back to the original static page below — so the
 * dynamic home is strictly additive and zero-risk.
 */
export default function Overview() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedViewId = searchParams.get('view')
  const defaultViewQ = useQuery({
    queryKey: ['default-view'],
    queryFn: views.default,
    enabled: !selectedViewId,
    retry: false,
    staleTime: 60_000,
  })
  const selectedViewQ = useQuery({
    queryKey: ['view', selectedViewId],
    queryFn: () => views.get(selectedViewId!),
    enabled: Boolean(selectedViewId),
    retry: false,
    staleTime: 60_000,
  })
  const listQ = useQuery({
    queryKey: ['views'],
    queryFn: views.list,
    staleTime: 30_000,
  })
  const view = selectedViewId ? selectedViewQ.data : defaultViewQ.data

  useEffect(() => {
    if (!selectedViewId && defaultViewQ.isSuccess) {
      qc.invalidateQueries({ queryKey: ['views'] })
    }
  }, [defaultViewQ.isSuccess, qc, selectedViewId])

  useEffect(() => {
    if (selectedViewId && selectedViewQ.isError) {
      setSearchParams({}, { replace: true })
      toast.error('That layout no longer exists. Showing Overview.')
    }
  }, [selectedViewId, selectedViewQ.isError, setSearchParams, toast])

  const duplicate = useMutation({
    mutationFn: () => {
      if (!view) throw new Error('Wait for the current layout to load.')
      return views.create({
        name: `${view.name} copy`.slice(0, 80),
        description: view.description,
        icon: view.icon,
        layout: view.layout,
      })
    },
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['views'] })
      setSearchParams({ view: created.id })
      toast.success(`Layout "${created.name}" created`)
    },
    onError: () => toast.error('Could not duplicate this layout'),
  })

  // A stored view is data, so renaming and deleting it are ordinary edits. The
  // API has always supported both (PATCH/DELETE /views/{id}); only the UI was
  // missing, which left every layout permanently named whatever created it.
  const [renameOpen, setRenameOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [draftName, setDraftName] = useState('')
  const [draftDescription, setDraftDescription] = useState('')

  const openRename = () => {
    if (!view) return
    setDraftName(view.name)
    setDraftDescription(view.description ?? '')
    setRenameOpen(true)
  }

  const cacheView = (updated: ViewDef) => {
    qc.setQueryData(['view', updated.id], updated)
    // The Overview may be the workspace default; keep that cache honest too, or
    // the header reverts to the old name until the next refetch.
    qc.setQueryData<ViewDef | undefined>(['default-view'], (current) =>
      current?.id === updated.id ? updated : current,
    )
    qc.invalidateQueries({ queryKey: ['views'] })
  }

  const rename = useMutation({
    mutationFn: () => {
      if (!view) throw new Error('Wait for the current layout to load.')
      const name = draftName.trim()
      if (!name) throw new Error('A layout needs a name.')
      return views.update(view.id, { name, description: draftDescription.trim() })
    },
    onSuccess: (updated) => {
      cacheView(updated)
      setRenameOpen(false)
      toast.success(`Renamed to "${updated.name}"`)
    },
    onError: (error: unknown) => toast.error(viewError(error, 'Could not rename this layout')),
  })

  const remove = useMutation({
    mutationFn: () => {
      if (!view) throw new Error('Wait for the current layout to load.')
      return views.remove(view.id).then(() => view)
    },
    onSuccess: (deleted) => {
      setDeleteOpen(false)
      // Drop the selection FIRST so the "layout no longer exists" effect below
      // never fires for a deletion the user just asked for.
      setSearchParams({}, { replace: true })
      qc.removeQueries({ queryKey: ['view', deleted.id] })
      qc.invalidateQueries({ queryKey: ['views'] })
      // Deleting the default Overview is recoverable: /views/default re-seeds a
      // fresh one on the next load, so this never leaves the page empty.
      qc.invalidateQueries({ queryKey: ['default-view'] })
      toast.success(`Layout "${deleted.name}" deleted`)
    },
    onError: (error: unknown) => toast.error(viewError(error, 'Could not delete this layout')),
  })

  // While loading, show the static page (it has its own skeletons) so there's
  // never a blank flash. On success, render the stored view. On error, the
  // static page is the permanent fallback.
  if (view && view.layout.length > 0) {
    const layouts = listQ.data ?? [view]
    return (
      <div className="space-y-6">
        <PageHeader
          screenLabel="Overview"
          eyebrow="Mission control"
          title={view.name}
          description={view.description || 'Live state of your pipeline — a view you can reshape.'}
          actions={
            <div className="flex flex-wrap items-center justify-end gap-2">
              <label className="sr-only" htmlFor="overview-layout">Overview layout</label>
              <select
                id="overview-layout"
                value={view.id}
                onChange={(event) => setSearchParams({ view: event.target.value })}
                className="min-w-44 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-700 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-brand-950"
                title="Switch Overview layout"
              >
                {!layouts.some((layout) => layout.id === view.id) && <option value={view.id}>{view.name}</option>}
                {layouts.map((layout) => <option key={layout.id} value={layout.id}>{layout.name}</option>)}
              </select>
              <Button variant="secondary" size="md" icon={Copy} isLoading={duplicate.isPending} onClick={() => duplicate.mutate()}>Duplicate layout</Button>
              <Button
                variant="secondary"
                size="md"
                icon={Pencil}
                onClick={openRename}
                aria-label={`Rename layout ${view.name}`}
                title="Rename this layout"
              />
              <Button
                variant="danger"
                size="md"
                icon={Trash2}
                onClick={() => setDeleteOpen(true)}
                aria-label={`Delete layout ${view.name}`}
                title="Delete this layout"
              />
              <Button variant="primary" size="md" icon={Plus} onClick={() => navigate('/campaigns')}>New campaign</Button>
            </div>
          }
        />
        <ComposableView
          key={view.id}
          view={view}
          label="Ask Overview"
          placeholder="Describe the mission-control view you need right now…"
          suggestions={[
            'Show active campaign health and recent errors',
            'Add approvals needing attention',
            'Show sends by status this week',
            'Focus on C1 and C2 operational state',
          ]}
        />

        <Modal title="Rename layout" open={renameOpen} onClose={() => setRenameOpen(false)} width="sm">
          <form
            onSubmit={(event) => { event.preventDefault(); rename.mutate() }}
            className="space-y-4"
          >
            <label className="block text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
              Name
              <input
                autoFocus
                value={draftName}
                maxLength={80}
                onChange={(event) => setDraftName(event.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-brand-950"
              />
            </label>
            <label className="block text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
              Description
              <input
                value={draftDescription}
                maxLength={200}
                placeholder="Optional — shown under the title"
                onChange={(event) => setDraftDescription(event.target.value)}
                className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-brand-950"
              />
            </label>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" size="md" onClick={() => setRenameOpen(false)}>Cancel</Button>
              <Button type="submit" variant="primary" size="md" isLoading={rename.isPending} disabled={!draftName.trim()}>Save</Button>
            </div>
          </form>
        </Modal>

        <Modal title="Delete layout" open={deleteOpen} onClose={() => setDeleteOpen(false)} width="sm">
          <div className="space-y-4">
            <div className="flex gap-2.5 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs leading-relaxed text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <p>
                Delete <strong>{view.name}</strong> and its {view.layout.length} widget{view.layout.length === 1 ? '' : 's'}? This cannot be undone.
              </p>
            </div>
            <p className="text-[11px] leading-relaxed text-slate-500">
              {layouts.length <= 1
                ? 'This is your only layout. A fresh default Overview will be created the next time this page loads.'
                : 'Only this layout is removed. Your campaigns, contacts, and sends are untouched.'}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="md" onClick={() => setDeleteOpen(false)}>Cancel</Button>
              <Button variant="danger" size="md" icon={Trash2} isLoading={remove.isPending} onClick={() => remove.mutate()}>Delete layout</Button>
            </div>
          </div>
        </Modal>
      </div>
    )
  }

  return <StaticOverview />
}

function StaticOverview() {
  const navigate = useNavigate()
  const contactsSummaryQ = useQuery({ queryKey: ['contacts-summary', {}], queryFn: () => projections.contactSummary() })
  const leadsSummaryQ = useQuery({ queryKey: ['leads-summary', 'all'], queryFn: () => projections.leadSummary() })
  const dealsQ = useQuery({ queryKey: ['deals', { limit: 1000 }], queryFn: () => projections.deals({ limit: 1000 }) })
  const threadsQ = useQuery({ queryKey: ['inbox-threads'], queryFn: () => inbox.threads(200) })
  const campaignsQ = useQuery({ queryKey: ['workflows'], queryFn: canvas.list })
  const scoresQ = useQuery({ queryKey: ['lead-scores', { limit: 6 }], queryFn: () => ai.scores({ limit: 6 }) })
  const scoresSummaryQ = useQuery({ queryKey: ['lead-scores-summary'], queryFn: ai.scoreSummary })

  // Stable reference so the openPipeline memo doesn't recompute every render.
  const deals = useMemo(() => dealsQ.data ?? [], [dealsQ.data])
  const threads = threadsQ.data ?? []
  const campaigns = campaignsQ.data ?? []
  const scores = scoresQ.data ?? []

  const activeCampaigns = campaigns.filter((c) => c.status === 'active').length
  const openPipeline = useMemo(
    () => deals.filter((d) => !d.stage.startsWith('closed')).reduce((s, d) => s + Number(d.value ?? 0), 0),
    [deals],
  )
  const contactsSummary = contactsSummaryQ.data
  const leadsSummary = leadsSummaryQ.data
  const scoresSummary = scoresSummaryQ.data

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Overview"
        eyebrow="Mission control"
        title="Overview"
        description="Live state of every contact, deal, campaign, and reply in your pipeline."
        actions={
          <>
            <Button variant="secondary" size="md" icon={Sparkles} onClick={() => navigate('/ai-studio')}>AI Studio</Button>
            <Button variant="primary" size="md" icon={Plus} onClick={() => navigate('/campaigns')}>New campaign</Button>
          </>
        }
      />

      {/* Primary stats */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Contacts" value={contactsSummaryQ.isLoading ? '—' : contactsSummary?.total ?? 0} icon={ContactIcon} accent="brand" hint="In your CRM" />
        <StatCard label="Active leads" value={leadsSummaryQ.isLoading ? '—' : leadsSummary?.active ?? 0} icon={Users} accent="emerald" hint={`${leadsSummary?.total ?? 0} prospects`} />
        <StatCard label="Open pipeline" value={dealsQ.isLoading ? '—' : `$${openPipeline.toLocaleString()}`} icon={KanbanSquare} accent="amber" hint={`${deals.length} deals`} />
        <StatCard label="Conversations" value={threadsQ.isLoading ? '—' : threads.length} icon={InboxIcon} accent="violet" hint="Open threads" />
      </section>

      {/* Secondary stats */}
      <section className="grid gap-4 sm:grid-cols-3">
        <StatCard label="Active campaigns" value={campaignsQ.isLoading ? '—' : activeCampaigns} icon={Megaphone} accent="emerald" hint={`${campaigns.length} total`} />
        <StatCard label="Hot leads (AI)" value={scoresSummaryQ.isLoading ? '—' : scoresSummary?.hot ?? 0} icon={Flame} accent="rose" hint="ICP score ≥ 70" />
        <StatCard label="Scored leads" value={scoresSummaryQ.isLoading ? '—' : scoresSummary?.total ?? 0} icon={Sparkles} accent="violet" hint="By AI Studio" />
      </section>

      {/* Pipeline + AI hot list */}
      <section className="grid gap-4 xl:grid-cols-2">
        <Card padding="lg">
          <CardHeader
            title="Deal pipeline"
            description="Value by stage"
            actions={<Button variant="ghost" size="sm" onClick={() => navigate('/deals')}>Open board</Button>}
          />
          {dealsQ.isLoading ? (
            <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-10 skeleton rounded-lg" />)}</div>
          ) : deals.length === 0 ? (
            <EmptyState icon={KanbanSquare} title="No deals yet" description="Deals appear as soon as a workflow creates one." />
          ) : (
            <PipelineBars deals={deals} />
          )}
        </Card>

        <Card padding="lg">
          <CardHeader
            title="Top scored leads"
            description="Best ICP fit, scored by AI"
            actions={<Badge label="AI" variant="violet" dot />}
          />
          {scoresQ.isLoading ? (
            <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-12 skeleton rounded-xl" />)}</div>
          ) : scores.length === 0 ? (
            <EmptyState icon={TrendingUp} title="No scored leads yet" description="Run a scoring job from AI Studio to rank your leads." action={<Button variant="primary" size="sm" icon={Sparkles} onClick={() => navigate('/ai-studio')}>Open AI Studio</Button>} />
          ) : (
            <div className="space-y-2">
              {[...scores].sort((a, b) => b.score - a.score).slice(0, 6).map((s) => (
                <ScoreRow key={s.lead_id} s={s} identity={s.identity ?? undefined} onClick={() => navigate('/leads')} />
              ))}
            </div>
          )}
        </Card>
      </section>

      {/* Campaigns at a glance */}
      <section>
        <Card padding="lg">
          <CardHeader title="Campaigns" description="Current state at a glance" actions={<Button variant="ghost" size="sm" onClick={() => navigate('/campaigns')}>All campaigns</Button>} />
          {campaignsQ.isLoading ? (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-20 skeleton rounded-xl" />)}</div>
          ) : campaigns.length === 0 ? (
            <EmptyState icon={Megaphone} title="No campaigns" description="Create one to start the pipeline." action={<Button variant="primary" size="sm" icon={Plus} onClick={() => navigate('/campaigns')}>Create campaign</Button>} />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {campaigns.slice(0, 6).map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => navigate(`/campaigns/${c.id}`)}
                  className="rounded-xl border border-slate-200 bg-slate-50/40 p-3 text-left transition-colors hover:bg-slate-100/60 dark:border-slate-800 dark:bg-slate-800/30 dark:hover:bg-slate-800/60"
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="truncate text-sm font-semibold text-slate-900 dark:text-white">{c.name}</p>
                    <Badge label={c.status} asStatus dot />
                  </div>
                  <p className="mt-1 text-[11px] uppercase tracking-[0.12em] text-slate-400">{c.timezone}</p>
                </button>
              ))}
            </div>
          )}
        </Card>
      </section>
    </div>
  )
}

function PipelineBars({ deals }: { deals: Deal[] }) {
  const byStage = useMemo(() => {
    const map = new Map<string, { count: number; value: number }>()
    for (const d of deals) {
      const cur = map.get(d.stage) ?? { count: 0, value: 0 }
      cur.count += 1
      cur.value += Number(d.value ?? 0)
      map.set(d.stage, cur)
    }
    return map
  }, [deals])
  const maxValue = Math.max(1, ...Array.from(byStage.values()).map((v) => v.value))
  const stages = DEAL_STAGE_ORDER.filter((s) => byStage.has(s)).concat(
    Array.from(byStage.keys()).filter((s) => !DEAL_STAGE_ORDER.includes(s)),
  )
  return (
    <div className="space-y-3">
      {stages.map((stage) => {
        const { count, value } = byStage.get(stage)!
        const pct = (value / maxValue) * 100
        return (
          <div key={stage}>
            <div className="flex items-center justify-between text-[12px]">
              <span className="font-medium capitalize text-slate-700 dark:text-slate-300">{stage.replace('_', ' ')}</span>
              <span className="text-slate-500">{count} · ${value.toLocaleString()}</span>
            </div>
            <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className={clsx('h-full rounded-full', stage === 'closed_won' ? 'bg-emerald-400' : stage === 'closed_lost' ? 'bg-rose-300' : 'bg-brand-400')}
                style={{ width: `${Math.max(4, pct)}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ScoreRow({ s, identity, onClick }: { s: LeadScore; identity?: string; onClick?: () => void }) {
  const tone = s.tier === 'hot' ? 'danger' : s.tier === 'warm' ? 'warning' : 'neutral'
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-3 rounded-xl border border-slate-200 bg-slate-50/40 p-2.5 text-left transition-colors hover:bg-slate-100/60 dark:border-slate-800 dark:bg-slate-800/30 dark:hover:bg-slate-800/60"
    >
      <div className={clsx(
        'flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg text-sm font-bold tabular-nums',
        s.tier === 'hot' ? 'bg-rose-50 text-rose-600' : s.tier === 'warm' ? 'bg-amber-50 text-amber-600' : 'bg-slate-100 text-slate-500',
      )}>
        {s.score}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
          {identity ?? 'Historical score'}
        </p>
        <p className="truncate text-[11px] text-slate-500">{s.reasons[0] ?? 'No reason recorded'}</p>
      </div>
      <Badge label={s.tier} variant={tone} dot />
    </button>
  )
}
