import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Target, Pause, Play, Trash2, Save, CheckCircle2, AlertTriangle, Loader2 } from 'lucide-react'
import { clsx } from 'clsx'
import {
  objectives,
  type Objective,
  type ObjectiveInput,
  type ObjectiveMetric,
  type ObjectiveStatus,
} from '../api/v2'
import Button from './Button'
import Badge from './Badge'
import Select from './Select'
import EmptyState from './EmptyState'
import { useToast } from './Toast'

// The campaign's first-class goal. The backend objective_controller reads this
// on every run-lead completion and pursues it — widening the audience and
// re-firing until the metric target is reached or the bounds envelope is spent.
// This panel is the operator surface: declare the goal, watch live progress,
// steer mid-flight (pause/resume), or clear it.

const METRIC_OPTIONS: { value: ObjectiveMetric; label: string; hint: string }[] = [
  { value: 'contacts', label: 'Contacts created', hint: 'People added to the CRM' },
  { value: 'qualified_leads', label: 'Qualified leads', hint: 'Leads that passed screening' },
  { value: 'companies', label: 'Companies sourced', hint: 'Accounts resolved into the CRM' },
  { value: 'replies', label: 'Replies received', hint: 'Inbound responses to outreach' },
]

const METRIC_LABEL: Record<ObjectiveMetric, string> = Object.fromEntries(
  METRIC_OPTIONS.map((o) => [o.value, o.label]),
) as Record<ObjectiveMetric, string>

const STATUS_META: Record<ObjectiveStatus, { variant: 'success' | 'warning' | 'info' | 'neutral'; label: string }> = {
  pursuing: { variant: 'info', label: 'Pursuing' },
  reached: { variant: 'success', label: 'Reached' },
  exhausted: { variant: 'warning', label: 'Exhausted' },
  paused: { variant: 'neutral', label: 'Paused' },
}

const inputClass =
  'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white'

interface ObjectivePanelProps {
  workflowId: string
}

export default function ObjectivePanel({ workflowId }: ObjectivePanelProps) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['objective', workflowId],
    queryFn: () => objectives.get(workflowId),
    // Poll while pursuing so live progress moves without a manual refresh.
    refetchInterval: (query) =>
      query.state.data?.status === 'pursuing' ? 8000 : false,
  })

  if (q.isLoading) {
    return (
      <div className="flex h-40 items-center justify-center text-slate-400">
        <Loader2 className="animate-spin" size={20} />
      </div>
    )
  }

  return q.data ? (
    <ObjectiveView
      objective={q.data}
      workflowId={workflowId}
      onChanged={() => qc.invalidateQueries({ queryKey: ['objective', workflowId] })}
    />
  ) : (
    <ObjectiveForm
      workflowId={workflowId}
      onSaved={() => qc.invalidateQueries({ queryKey: ['objective', workflowId] })}
    />
  )
}

// ── Live view ─────────────────────────────────────────────────────────────────

function ObjectiveView({
  objective,
  workflowId,
  onChanged,
}: {
  objective: Objective
  workflowId: string
  onChanged: () => void
}) {
  const toast = useToast()
  const [editing, setEditing] = useState(false)

  const pauseMut = useMutation({
    mutationFn: () => objectives.togglePause(workflowId),
    onSuccess: (o) => {
      toast.success(o.status === 'paused' ? 'Pursuit paused' : 'Pursuit resumed')
      onChanged()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not toggle pause'),
  })
  const clearMut = useMutation({
    mutationFn: () => objectives.clear(workflowId),
    onSuccess: () => {
      toast.success('Objective cleared')
      onChanged()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not clear objective'),
  })

  if (editing) {
    return (
      <ObjectiveForm
        workflowId={workflowId}
        initial={objective}
        onSaved={() => {
          setEditing(false)
          onChanged()
        }}
        onCancel={() => setEditing(false)}
      />
    )
  }

  const current = Number(objective.progress.current ?? 0)
  const pct = objective.target > 0 ? Math.min(100, Math.round((current / objective.target) * 100)) : 0
  const status = STATUS_META[objective.status] ?? STATUS_META.pursuing
  const isTerminal = objective.status === 'reached' || objective.status === 'exhausted'
  const iterations = Number(objective.progress.iterations_used ?? 0)
  const maxIterations = Number(objective.bounds.max_iterations ?? 0)
  const spend = Number(objective.progress.spend_usd ?? 0)
  const maxSpend = objective.bounds.max_spend_usd

  const barColor =
    objective.status === 'reached'
      ? 'bg-emerald-500'
      : objective.status === 'exhausted'
        ? 'bg-amber-500'
        : objective.status === 'paused'
          ? 'bg-slate-400'
          : 'bg-brand-500'

  return (
    <div className="space-y-5">
      {/* Goal headline + status */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-900/30 dark:text-brand-300">
            <Target size={20} />
          </span>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-wider text-brand-500">Campaign goal</p>
            <p className="text-lg font-bold text-slate-900 dark:text-white">
              {objective.target.toLocaleString()} {METRIC_LABEL[objective.metric] ?? objective.metric}
            </p>
            <p className="mt-0.5 text-xs text-slate-500">
              The engine sources, screens & widens autonomously until this is reached.
            </p>
          </div>
        </div>
        <Badge label={status.label} variant={status.variant} dot />
      </div>

      {/* Progress bar */}
      <div>
        <div className="mb-1 flex items-baseline justify-between">
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-200">
            {current.toLocaleString()}
            <span className="text-slate-400"> / {objective.target.toLocaleString()}</span>
          </span>
          <span className="text-xs font-medium text-slate-400">{pct}%</span>
        </div>
        <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
          <div
            className={clsx('h-full rounded-full transition-all duration-700', barColor)}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Terminal banner */}
      {objective.status === 'reached' && (
        <div className="flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300">
          <CheckCircle2 size={16} /> Goal reached — pursuit stopped.
        </div>
      )}
      {objective.status === 'exhausted' && (
        <div className="flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
          <AlertTriangle size={16} /> Bounds spent before the goal was reached. Widen the audience or raise the limits.
        </div>
      )}

      {/* Telemetry */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Iterations" value={maxIterations ? `${iterations} / ${maxIterations}` : String(iterations)} />
        <Stat
          label="Spend"
          value={`$${spend.toFixed(2)}${maxSpend != null ? ` / $${Number(maxSpend).toFixed(2)}` : ''}`}
        />
        <Stat label="Last action" value={objective.progress.last_action ?? '—'} />
      </div>

      {/* Audience summary */}
      {Array.isArray(objective.audience.keywords) && objective.audience.keywords.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">Audience ladder</p>
          <div className="flex flex-wrap gap-1.5">
            {objective.audience.keywords.map((kw, i) => (
              <Badge key={`${kw}-${i}`} label={String(kw)} variant={i === 0 ? 'brand' : 'neutral'} size="sm" />
            ))}
          </div>
          {objective.audience.location && (
            <p className="mt-1.5 text-xs text-slate-400">Location: {String(objective.audience.location)}</p>
          )}
        </div>
      )}

      {/* Recourse */}
      <div className="flex items-center justify-between gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        <Button variant="danger" size="sm" icon={Trash2} onClick={() => clearMut.mutate()} isLoading={clearMut.isPending}>
          Clear goal
        </Button>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
            Edit
          </Button>
          {!isTerminal && (
            <Button
              variant="secondary"
              size="sm"
              icon={objective.status === 'paused' ? Play : Pause}
              onClick={() => pauseMut.mutate()}
              isLoading={pauseMut.isPending}
            >
              {objective.status === 'paused' ? 'Resume' : 'Pause'}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2 dark:bg-slate-800/50">
      <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-0.5 truncate text-sm font-semibold text-slate-700 dark:text-slate-200">{value}</p>
    </div>
  )
}

// ── Declare / edit form ─────────────────────────────────────────────────────────

function ObjectiveForm({
  workflowId,
  initial,
  onSaved,
  onCancel,
}: {
  workflowId: string
  initial?: Objective
  onSaved: () => void
  onCancel?: () => void
}) {
  const toast = useToast()
  const [metric, setMetric] = useState<ObjectiveMetric>(initial?.metric ?? 'contacts')
  const [target, setTarget] = useState(String(initial?.target ?? 50))
  const [keywords, setKeywords] = useState((initial?.audience.keywords ?? []).join(', '))
  const [location, setLocation] = useState(String(initial?.audience.location ?? ''))
  const [maxIterations, setMaxIterations] = useState(String(initial?.bounds.max_iterations ?? 5))
  const [maxSpend, setMaxSpend] = useState(initial?.bounds.max_spend_usd != null ? String(initial.bounds.max_spend_usd) : '')

  const targetNum = Number(target)
  const valid = Number.isInteger(targetNum) && targetNum > 0 && targetNum <= 100_000

  const payload = useMemo<ObjectiveInput>(() => {
    const kws = keywords.split(',').map((s) => s.trim()).filter(Boolean)
    return {
      metric,
      target: targetNum,
      audience: {
        ...(kws.length > 0 ? { keywords: kws } : {}),
        ...(location.trim() ? { location: location.trim() } : {}),
      },
      bounds: {
        ...(Number(maxIterations) > 0 ? { max_iterations: Number(maxIterations) } : {}),
        ...(maxSpend.trim() && Number(maxSpend) > 0 ? { max_spend_usd: Number(maxSpend) } : {}),
      },
    }
  }, [metric, targetNum, keywords, location, maxIterations, maxSpend])

  const saveMut = useMutation({
    mutationFn: () => objectives.set(workflowId, payload),
    onSuccess: () => {
      toast.success(initial ? 'Objective updated' : 'Objective set — the engine will pursue it')
      onSaved()
    },
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not save objective'),
  })

  return (
    <div className="space-y-5">
      {!initial && (
        <EmptyState
          icon={Target}
          title="No goal set"
          description="Declare what this campaign should achieve. The engine sources, screens, and widens the audience on its own — re-running until the target is reached or your safety bounds are spent."
        />
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
          Metric
          <Select
            className="mt-1"
            ariaLabel="Goal metric"
            value={metric}
            onChange={(v) => setMetric(v as ObjectiveMetric)}
            options={METRIC_OPTIONS}
          />
        </label>
        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
          Target
          <input
            className={`mt-1 ${inputClass}`}
            type="number"
            min={1}
            max={100000}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="50"
          />
        </label>
      </div>

      <div className="space-y-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
        <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Audience</p>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
          Keywords <span className="text-slate-400">(comma-separated; widens in order)</span>
          <input
            className={`mt-1 ${inputClass}`}
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder="VP Marketing, Marketing Director, Head of Growth"
          />
        </label>
        <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
          Location <span className="text-slate-400">(optional)</span>
          <input
            className={`mt-1 ${inputClass}`}
            value={location}
            onChange={(e) => setLocation(e.target.value)}
            placeholder="India"
          />
        </label>
      </div>

      <div className="space-y-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
        <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">Safety bounds</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
            Max iterations
            <input
              className={`mt-1 ${inputClass}`}
              type="number"
              min={1}
              value={maxIterations}
              onChange={(e) => setMaxIterations(e.target.value)}
              placeholder="5"
            />
          </label>
          <label className="block text-xs font-medium text-slate-600 dark:text-slate-300">
            Max spend (USD) <span className="text-slate-400">(optional)</span>
            <input
              className={`mt-1 ${inputClass}`}
              type="number"
              min={0}
              step="0.5"
              value={maxSpend}
              onChange={(e) => setMaxSpend(e.target.value)}
              placeholder="no cap"
            />
          </label>
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel} disabled={saveMut.isPending}>
            Cancel
          </Button>
        )}
        <Button
          variant="primary"
          size="sm"
          icon={Save}
          onClick={() => saveMut.mutate()}
          isLoading={saveMut.isPending}
          disabled={!valid}
        >
          {initial ? 'Update goal' : 'Set goal'}
        </Button>
      </div>
    </div>
  )
}
