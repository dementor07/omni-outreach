import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BarChart3, TrendingUp, Send, MessageSquare, Building2, Users, DollarSign, Sparkles } from 'lucide-react'
import { clsx } from 'clsx'
import { projections, inbox, ai } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card, { CardHeader } from '../components/Card'
import EmptyState from '../components/EmptyState'

export default function Analytics() {
  const leadsQ = useQuery({ queryKey: ['leads'], queryFn: () => projections.leads({ limit: 2000 }) })
  const dealsQ = useQuery({ queryKey: ['deals'], queryFn: () => projections.deals({ limit: 2000 }) })
  const threadsQ = useQuery({ queryKey: ['inbox-threads'], queryFn: () => inbox.threads(200) })
  const scoresQ = useQuery({ queryKey: ['lead-scores'], queryFn: () => ai.scores({ limit: 2000 }) })
  const effQ = useQuery({ queryKey: ['analytics-summary'], queryFn: projections.analytics })

  const leads = leadsQ.data ?? []
  const deals = dealsQ.data ?? []
  const threads = threadsQ.data ?? []
  const scores = useMemo(() => scoresQ.data ?? [], [scoresQ.data])

  // Funnel: leads → replied → converted → deals → won. "Converted" is the
  // flow.goal outcome (lead.status === 'converted'), distinct from a deal win.
  const total = leads.length
  const replied = leads.filter((l) => l.status === 'replied').length
  const converted = leads.filter((l) => l.status === 'converted').length
  const dealsCount = deals.length
  const won = deals.filter((d) => d.stage === 'closed_won').length
  const funnel = [
    { label: 'Leads', value: total, color: 'bg-brand-400' },
    { label: 'Replied', value: replied, color: 'bg-violet-400' },
    { label: 'Converted', value: converted, color: 'bg-sky-400' },
    { label: 'Deals', value: dealsCount, color: 'bg-amber-400' },
    { label: 'Won', value: won, color: 'bg-emerald-400' },
  ]
  const funnelMax = Math.max(1, ...funnel.map((f) => f.value))

  const tierDist = useMemo(() => {
    const d = { hot: 0, warm: 0, cold: 0 }
    for (const s of scores) d[s.tier] += 1
    return d
  }, [scores])

  const replyRate = total > 0 ? Math.round((replied / total) * 100) : 0
  const winRate = dealsCount > 0 ? Math.round((won / dealsCount) * 100) : 0

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Analytics"
        eyebrow="Intelligence"
        title="Analytics"
        description="Conversion funnel, reply rates, and AI lead-quality distribution across your pipeline."
      />

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total leads" value={total} icon={TrendingUp} accent="brand" />
        <StatCard label="Reply rate" value={`${replyRate}%`} icon={MessageSquare} accent="violet" hint={`${replied} replied`} />
        <StatCard label="Win rate" value={`${winRate}%`} icon={Send} accent="emerald" hint={`${won} of ${dealsCount} deals`} />
        <StatCard label="Conversations" value={threads.length} icon={MessageSquare} accent="amber" />
      </section>

      <section className="grid gap-4 xl:grid-cols-2">
        <Card padding="lg">
          <CardHeader title="Conversion funnel" description="Leads → Replied → Converted → Deals → Won" />
          {total === 0 ? (
            <EmptyState icon={BarChart3} title="No funnel data yet" description="Funnels populate once leads enter your campaigns." />
          ) : (
            <div className="space-y-3">
              {funnel.map((f) => (
                <div key={f.label}>
                  <div className="flex items-center justify-between text-[12px]">
                    <span className="font-medium text-slate-700 dark:text-slate-300">{f.label}</span>
                    <span className="tabular-nums text-slate-500">{f.value.toLocaleString()}</span>
                  </div>
                  <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div className={clsx('h-full rounded-full transition-all', f.color)} style={{ width: `${Math.max(3, (f.value / funnelMax) * 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card padding="lg">
          <CardHeader title="AI lead quality" description="ICP tier distribution from AI scoring" />
          {scores.length === 0 ? (
            <EmptyState icon={BarChart3} title="No scored leads" description="Run a scoring job in AI Studio to see quality distribution." />
          ) : (
            <div className="space-y-3">
              {([['hot', 'bg-rose-400'], ['warm', 'bg-amber-400'], ['cold', 'bg-slate-300']] as const).map(([tier, color]) => {
                const v = tierDist[tier]
                const pct = scores.length ? Math.round((v / scores.length) * 100) : 0
                return (
                  <div key={tier}>
                    <div className="flex items-center justify-between text-[12px]">
                      <span className="font-medium capitalize text-slate-700 dark:text-slate-300">{tier}</span>
                      <span className="tabular-nums text-slate-500">{v} ({pct}%)</span>
                    </div>
                    <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                      <div className={clsx('h-full rounded-full', color)} style={{ width: `${Math.max(3, pct)}%` }} />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </section>

      {/* T2 — lead-gen efficiency + cost (omni_pipeline_metrics rollup) */}
      <section>
        <Card padding="lg">
          <CardHeader title="Lead-gen efficiency & cost" description="Across all source runs in this workspace" />
          {!effQ.data || effQ.data.runs === 0 ? (
            <EmptyState icon={DollarSign} title="No source runs yet" description="Run a lead-gen source (Naukri, Serper, …) to see funnel volumes and AI/Serper cost." />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatCard label="Companies collected" value={effQ.data.companies_collected.toLocaleString()} icon={Building2} accent="brand" hint={`${effQ.data.companies_qualified} qualified · ${effQ.data.companies_rejected} rejected`} />
              <StatCard label="People found" value={effQ.data.people_found.toLocaleString()} icon={Users} accent="violet" hint={`${effQ.data.people_verified} verified`} />
              <StatCard label="Leads created" value={effQ.data.leads_created.toLocaleString()} icon={TrendingUp} accent="emerald" hint={`${effQ.data.runs} runs`} />
              <StatCard label="Total cost" value={`$${effQ.data.total_cost.toFixed(2)}`} icon={DollarSign} accent="amber" hint={`${effQ.data.serper_calls} Serper · ${effQ.data.claude_calls} Claude calls`} />
              <StatCard label="Claude tokens" value={(effQ.data.claude_input_tokens + effQ.data.claude_output_tokens).toLocaleString()} icon={Sparkles} accent="violet" hint={`${effQ.data.claude_input_tokens.toLocaleString()} in · ${effQ.data.claude_output_tokens.toLocaleString()} out`} />
            </div>
          )}
        </Card>
      </section>
    </div>
  )
}
