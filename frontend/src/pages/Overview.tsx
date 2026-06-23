import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Users, Contact as ContactIcon, KanbanSquare, Inbox as InboxIcon,
  Megaphone, Sparkles, Plus, TrendingUp, Flame,
} from 'lucide-react'
import { clsx } from 'clsx'
import { projections, inbox, canvas, ai, type Deal, type LeadScore } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card, { CardHeader } from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'

const DEAL_STAGE_ORDER = ['lead', 'qualified', 'meeting', 'proposal', 'closed_won', 'closed_lost']

export default function Overview() {
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
