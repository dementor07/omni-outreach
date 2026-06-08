import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles, Gauge, PenLine, Database, Tag, Play, ShieldCheck } from 'lucide-react'
import { clsx } from 'clsx'
import { ai, type AiJob, type AiJobKind } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card, { CardHeader } from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { timeAgo } from '../lib/format'

const KIND_META: Record<AiJobKind, { label: string; icon: React.ElementType; desc: string }> = {
  score: { label: 'Lead scoring', icon: Gauge, desc: 'Rank leads 0–100 against your ICP' },
  compose: { label: 'AI compose', icon: PenLine, desc: 'Draft personalised outreach copy' },
  enrich: { label: 'Enrichment', icon: Database, desc: 'Fill missing contact/company fields' },
  classify: { label: 'Classify', icon: Tag, desc: 'Label inbound replies by intent' },
  // Screening runs inside a workflow (ai.screen_company / ai.screen_person), not
  // as an ad-hoc job — so it appears in the run log but not the launcher tiles.
  screen: { label: 'ICP screen', icon: ShieldCheck, desc: 'Claude ACCEPT/REJECT against your ICP (runs in-workflow)' },
}

// Kinds an operator can launch ad-hoc from AI Studio (screen is workflow-only).
const LAUNCHABLE_KINDS: AiJobKind[] = ['score', 'compose', 'enrich', 'classify']

export default function AiStudio() {
  const qc = useQueryClient()
  const { data: jobs = [], isLoading } = useQuery({
    queryKey: ['ai-jobs'],
    queryFn: () => ai.jobs({ limit: 100 }),
    refetchInterval: 5000,
  })

  const [icp, setIcp] = useState('B2B SaaS, VP Sales or RevOps, 50–500 employees, US/EU')
  const runScore = useMutation({
    mutationFn: () =>
      ai.runJob({ kind: 'score', entity_type: 'lead', config: { icp_description: icp } }),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['ai-jobs'] }), 600),
  })

  const done = jobs.filter((j) => j.status === 'done').length
  const running = jobs.filter((j) => j.status === 'queued' || j.status === 'running').length

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="AI Studio"
        eyebrow="Intelligence"
        title="AI Studio"
        description="Run scoring, compose, enrichment, and classification jobs. Every run is auditable."
        actions={<Badge label="AI" variant="violet" dot />}
      />

      <section className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Total runs" value={isLoading ? '—' : jobs.length} icon={Sparkles} accent="violet" />
        <StatCard label="Completed" value={isLoading ? '—' : done} icon={Gauge} accent="emerald" />
        <StatCard label="In flight" value={isLoading ? '—' : running} icon={Play} accent="amber" />
      </section>

      {/* Job launchers */}
      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {LAUNCHABLE_KINDS.map((kind) => {
          const m = KIND_META[kind]
          const Icon = m.icon
          return (
            <Card key={kind} padding="md">
              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-50 text-violet-600 dark:bg-violet-900/30">
                <Icon size={16} />
              </span>
              <p className="mt-3 text-sm font-semibold text-slate-900 dark:text-white">{m.label}</p>
              <p className="mt-0.5 text-xs text-slate-500">{m.desc}</p>
            </Card>
          )
        })}
      </section>

      {/* Score launcher */}
      <Card padding="lg">
        <CardHeader title="Run lead scoring" description="Score all active leads against an ICP rubric using your connected AI provider." />
        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">ICP description</span>
          <textarea
            rows={3}
            value={icp}
            onChange={(e) => setIcp(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
        <div className="mt-3 flex justify-end">
          <Button variant="primary" icon={Play} onClick={() => runScore.mutate()} isLoading={runScore.isPending} disabled={!icp.trim()}>
            Run scoring
          </Button>
        </div>
      </Card>

      {/* Run log */}
      <Card padding="none">
        <div className="border-b border-slate-100 px-5 py-3 dark:border-slate-800">
          <p className="text-sm font-semibold text-slate-900 dark:text-white">Run log</p>
        </div>
        {isLoading ? (
          <div className="space-y-2 p-4">{[0, 1, 2].map((i) => <div key={i} className="h-10 skeleton rounded-lg" />)}</div>
        ) : jobs.length === 0 ? (
          <EmptyState icon={Sparkles} title="No AI runs yet" description="Kick a job above — it'll show here with status, model, and cost." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 text-xs uppercase tracking-wider text-slate-500 dark:border-slate-800">
                <tr>
                  <th className="px-5 py-2 font-medium">Kind</th>
                  <th className="px-5 py-2 font-medium">Status</th>
                  <th className="px-5 py-2 font-medium">Model</th>
                  <th className="px-5 py-2 font-medium">Cost</th>
                  <th className="px-5 py-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {jobs.map((j) => <JobRow key={j.id} job={j} />)}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}

function JobRow({ job }: { job: AiJob }) {
  const statusTone =
    job.status === 'done' ? 'success' : job.status === 'failed' ? 'danger' : job.status === 'running' ? 'info' : 'warning'
  const Icon = KIND_META[job.kind].icon
  return (
    <tr className="hover:bg-slate-50 dark:hover:bg-slate-900/50">
      <td className="px-5 py-2.5">
        <div className="flex items-center gap-2">
          <Icon size={14} className="text-violet-500" />
          <span className="font-medium text-slate-900 dark:text-white">{KIND_META[job.kind].label}</span>
        </div>
      </td>
      <td className="px-5 py-2.5"><Badge label={job.status} variant={statusTone} size="xs" dot /></td>
      <td className="px-5 py-2.5 text-slate-500">{job.model ?? '—'}</td>
      <td className={clsx('px-5 py-2.5 tabular-nums', job.cost_usd ? 'text-slate-700 dark:text-slate-300' : 'text-slate-300')}>
        {job.cost_usd ? `$${Number(job.cost_usd).toFixed(4)}` : '—'}
      </td>
      <td className="px-5 py-2.5 text-slate-400">{timeAgo(job.created_at)}</td>
    </tr>
  )
}
