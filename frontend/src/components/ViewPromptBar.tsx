import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, AlertTriangle, Bot, Braces, Cable, Check, Copy, MessageSquarePlus, Radio, RefreshCw, SlidersHorizontal, Sparkles, Terminal, Upload, X } from 'lucide-react'
import {
  agentHarness,
  views,
  type AgentHarnessJob,
  type AgentHarnessWidgetReview,
  type ViewAuthoringConnection,
  type ViewCandidate,
  type ViewDef,
} from '../api/v2'
import type { WidgetAnnotation } from './ViewWidgets'
import Button from './Button'
import Card from './Card'
import { useToast } from './Toast'

interface Props {
  view: ViewDef
  label?: string
  placeholder?: string
  suggestions?: string[]
  annotationMode: boolean
  annotations: WidgetAnnotation[]
  onToggleAnnotationMode: () => void
  onClearAnnotations: () => void
  onUpdated?: (view: ViewDef) => void
  expanded: boolean
  onExpand: () => void
  onClose: () => void
}

type AuthoringSource = 'connection' | 'harness'
const TERMINAL_JOB_STATES = new Set(['succeeded', 'failed', 'cancelled', 'expired'])
const SOURCE_STORAGE_KEY = 'omni:view-authoring-source'

function initialSource(): AuthoringSource {
  return localStorage.getItem(SOURCE_STORAGE_KEY) === 'harness' ? 'harness' : 'connection'
}

function errorDetail(error: unknown, fallback: string): string {
  return (
    (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    (error instanceof Error ? error.message : fallback)
  )
}

function providerLabel(connection: ViewAuthoringConnection): string {
  const names: Record<string, string> = {
    anthropic: 'Anthropic',
    openai: 'OpenAI',
    openrouter: 'OpenRouter',
    gemini: 'Gemini',
    openai_compatible: 'OpenAI-compatible',
  }
  return `${names[connection.provider] ?? connection.provider} · ${connection.name}`
}

function shortTime(value: string | null | undefined): string {
  if (!value) return 'not reported'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'not reported' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function reviewRows(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return 'No rows'
  const visible = rows.length === 1 ? rows[0] : rows.slice(0, 3)
  const suffix = rows.length > 3 ? `\n… ${rows.length - 3} more rows` : ''
  return `${JSON.stringify(visible, null, 2)}${suffix}`
}

function WidgetReview({ change }: { change: AgentHarnessWidgetReview }) {
  const renamed = change.before_title !== change.after_title
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-950/60">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono text-[10px] font-bold text-slate-500">#{change.widget_id}</p>
          <p className="mt-0.5 text-xs font-bold text-slate-800 dark:text-slate-100">
            {renamed ? <><span className="text-slate-500 line-through">{change.before_title || 'Untitled'}</span><span className="mx-1.5 text-slate-400">→</span>{change.after_title || 'Untitled'}</> : change.after_title || change.before_title || 'Untitled widget'}
          </p>
        </div>
        <span className={`rounded-full px-2 py-1 text-[9px] font-bold ${change.query_changed ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
          {change.query_changed ? 'Query changed' : 'Presentation only'}
        </span>
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-2">
        <div>
          <p className="mb-1 text-[9px] font-bold uppercase tracking-[0.1em] text-slate-500">Current result</p>
          <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-100 px-2.5 py-2 text-[10px] leading-relaxed text-slate-700 dark:bg-slate-900 dark:text-slate-300">{reviewRows(change.before_rows)}</pre>
        </div>
        <div>
          <p className="mb-1 text-[9px] font-bold uppercase tracking-[0.1em] text-emerald-700 dark:text-emerald-300">Proposed result</p>
          <pre className="max-h-36 overflow-auto whitespace-pre-wrap rounded-lg bg-emerald-50 px-2.5 py-2 text-[10px] leading-relaxed text-emerald-950 dark:bg-emerald-950/30 dark:text-emerald-200">{reviewRows(change.after_rows)}</pre>
        </div>
      </div>
    </div>
  )
}

function ProposalReview({
  job,
  candidate,
  isApplying,
  onApply,
  onStartFresh,
}: {
  job: AgentHarnessJob
  candidate: ViewCandidate
  isApplying: boolean
  onApply: () => void
  onStartFresh: () => void
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
        <p className="flex items-center gap-1.5 text-xs font-bold text-emerald-800 dark:text-emerald-200"><Check size={13} /> Structurally valid proposal</p>
        <p className="mt-1 text-[10px] leading-relaxed text-emerald-700 dark:text-emerald-300"><strong>{candidate.name}</strong> · {candidate.layout.length} widgets · authored by {job.origin === 'connection' ? 'connected API' : job.origin === 'import' ? 'manual import' : 'agent harness'}. Nothing has been applied. Review the live evidence below.</p>
      </div>

      {!job.review?.captured_at ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
          <p className="flex items-center gap-1.5 font-bold"><AlertTriangle size={13} /> Live query review unavailable</p>
          <p className="mt-1 text-[10px] leading-relaxed">Omni has not supplied before/after query results for this proposal. Apply remains disabled; create a fresh grounded proposal.</p>
        </div>
      ) : (
        <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/45">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">Live query review</p>
              <p className="mt-1 text-[10px] text-slate-500">Captured {new Date(job.review.captured_at).toLocaleString()} against this unapplied proposal.</p>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-[9px] font-bold ${job.review.all_queries_valid ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300'}`}>
              {job.review.all_queries_valid ? 'All queries ran' : 'Query execution failed'}
            </span>
          </div>
          {(job.review.blocking_issues ?? []).length > 0 && (
            <div className="space-y-1 rounded-lg border border-rose-200 bg-rose-50 px-2.5 py-2 text-[10px] text-rose-900 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
              {(job.review.blocking_issues ?? []).map((issue, index) => <p key={`${issue.code}-${index}`} className="flex gap-1.5"><AlertTriangle size={11} className="mt-0.5 shrink-0" /><span>{issue.message}</span></p>)}
            </div>
          )}
          {(job.review.warnings ?? []).length > 0 && (
            <div className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 text-[10px] text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
              {(job.review.warnings ?? []).map((warning, index) => <p key={`${warning.code}-${index}`} className="flex gap-1.5"><AlertTriangle size={11} className="mt-0.5 shrink-0" /><span>{warning.message}</span></p>)}
            </div>
          )}
          {(job.review.changed_widgets ?? []).length > 0 ? (job.review.changed_widgets ?? []).map((change) => (
            <WidgetReview key={change.widget_id} change={change} />
          )) : (
            <p className="rounded-lg bg-white px-2.5 py-2 text-[10px] text-slate-500 dark:bg-slate-900">No widget-level result changes were reported.</p>
          )}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" icon={Upload} isLoading={isApplying} disabled={isApplying || !job.review?.ready_to_apply} onClick={onApply}>Apply reviewed proposal</Button>
        <Button variant="secondary" size="sm" icon={RefreshCw} disabled={isApplying} onClick={onStartFresh}>Discard & start fresh</Button>
      </div>
    </div>
  )
}

export default function ViewPromptBar({
  view,
  label = 'Author this view',
  placeholder = 'Describe the operational view you need…',
  suggestions = [],
  annotationMode,
  annotations,
  onToggleAnnotationMode,
  onClearAnnotations,
  onUpdated,
  expanded,
  onExpand,
  onClose,
}: Props) {
  const qc = useQueryClient()
  const toast = useToast()
  const [source, setSource] = useState<AuthoringSource>(initialSource)
  const [instruction, setInstruction] = useState('')
  const [connectionId, setConnectionId] = useState('')
  const [model, setModel] = useState('')
  const [candidateText, setCandidateText] = useState('')
  const [validatedCandidate, setValidatedCandidate] = useState<ViewCandidate | null>(null)
  const [activeJobId, setActiveJobId] = useState<string | null>(null)
  const [selectedHarnessId, setSelectedHarnessId] = useState('')
  const [submittedInstruction, setSubmittedInstruction] = useState('')
  const [submittedHarnessId, setSubmittedHarnessId] = useState('')
  const [submittedAnnotationCount, setSubmittedAnnotationCount] = useState(0)
  const [dismissedJobIds, setDismissedJobIds] = useState<Set<string>>(() => new Set())

  const connectionsQ = useQuery({
    queryKey: ['view-authoring-connections'],
    queryFn: views.authoringConnections,
    staleTime: 60_000,
  })
  const catalogQ = useQuery({
    queryKey: ['view-widget-catalog'],
    queryFn: views.widgetCatalog,
    enabled: source === 'harness',
    staleTime: 5 * 60_000,
  })
  const workersQ = useQuery({
    queryKey: ['agent-harness-worker-status'],
    queryFn: agentHarness.workerStatus,
    enabled: source === 'harness',
    refetchInterval: source === 'harness' ? 2_000 : false,
  })
  const openProposalQ = useQuery({
    queryKey: ['view-open-proposal', view.id],
    queryFn: () => views.openProposal(view.id),
    // Every authoring path creates the same durable proposal. Recovery must not
    // depend on whichever source toggle survived a browser refresh or where the
    // proposal happens to fall in a bounded workspace job history.
    enabled: !activeJobId,
    staleTime: 5_000,
  })
  const jobQ = useQuery({
    queryKey: ['agent-harness-job', activeJobId],
    queryFn: () => agentHarness.job(activeJobId!),
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const job = query.state.data as AgentHarnessJob | undefined
      return job && TERMINAL_JOB_STATES.has(job.status) ? false : 1_200
    },
  })
  const connections = useMemo(() => connectionsQ.data ?? [], [connectionsQ.data])
  const workers = useMemo(() => workersQ.data?.workers ?? [], [workersQ.data?.workers])
  const presenceAvailable = workersQ.data?.available ?? false
  const activeJob = jobQ.data
  const selectedConnection = connections.find((connection) => connection.id === connectionId)
  const draftLocked = Boolean(
    activeJob && !activeJob.applied_at && ['queued', 'working', 'succeeded'].includes(activeJob.status),
  )
  const leaseExpired = Boolean(
    activeJob?.status === 'working' &&
    activeJob.lease_expires_at &&
    new Date(activeJob.lease_expires_at).getTime() <= Date.now(),
  )
  const liveJobWorker = activeJob?.harness_id
    ? workers.find((worker) =>
        worker.harness_id === activeJob.harness_id &&
        worker.job_id === activeJob.id &&
        worker.state === 'working' &&
        new Date(worker.active_until).getTime() > Date.now(),
      )
    : undefined
  const activelyWorking = activeJob?.status === 'working' && !leaseExpired && Boolean(liveJobWorker)

  useEffect(() => {
    localStorage.setItem(SOURCE_STORAGE_KEY, source)
  }, [source])

  useEffect(() => {
    if (connections.length === 0) return
    const selected = connections.find((connection) => connection.id === connectionId) ?? connections[0]
    if (selected.id !== connectionId) setConnectionId(selected.id)
  }, [connectionId, connections])

  useEffect(() => {
    if (selectedConnection?.default_model) setModel(selectedConnection.default_model)
  }, [selectedConnection?.id, selectedConnection?.default_model])

  useEffect(() => {
    if (workers.length === 0) {
      setSelectedHarnessId('')
      return
    }
    if (!workers.some((worker) => worker.harness_id === selectedHarnessId)) {
      setSelectedHarnessId(workers[0].harness_id)
    }
  }, [selectedHarnessId, workers])

  useEffect(() => {
    if (activeJob?.status === 'succeeded' && activeJob.result) {
      setValidatedCandidate(activeJob.result as ViewCandidate)
    }
  }, [activeJob?.id, activeJob?.result, activeJob?.status])

  useEffect(() => {
    if (activeJobId) return
    const recoverable = openProposalQ.data
    if (recoverable && dismissedJobIds.has(recoverable.id)) return
    if (recoverable) setActiveJobId(recoverable.id)
  }, [activeJobId, dismissedJobIds, openProposalQ.data])

  useEffect(() => {
    if (!activeJob) return
    if (activeJob.requested_harness_id) setSubmittedHarnessId(activeJob.requested_harness_id)
    setSource(activeJob.origin === 'connection' ? 'connection' : 'harness')
  }, [activeJob])

  const finishUpdate = (updated: ViewDef, appliedHarnessJobId: string | null) => {
    qc.setQueryData(['view', view.id], updated)
    qc.setQueryData<ViewDef | undefined>(['default-view'], (current) => current?.id === updated.id ? updated : current)
    qc.invalidateQueries({ queryKey: ['view-widget'] })
    qc.invalidateQueries({ queryKey: ['views'] })
    setInstruction('')
    setCandidateText('')
    setValidatedCandidate(null)
    if (appliedHarnessJobId) {
      qc.setQueryData<AgentHarnessJob[]>(['agent-harness-jobs'], (jobs) =>
        jobs?.map((job) => job.id === appliedHarnessJobId ? { ...job, applied_at: new Date().toISOString() } : job),
      )
      setActiveJobId(null)
      setSubmittedInstruction('')
      setSubmittedHarnessId('')
      setSubmittedAnnotationCount(0)
    }
    qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
    qc.invalidateQueries({ queryKey: ['view-open-proposal', view.id] })
    onClearAnnotations()
    onUpdated?.(updated)
    toast.success('View updated')
  }

  const apply = useMutation({
    mutationFn: async () => {
      if (!validatedCandidate) throw new Error('Validate the agent-authored ViewSpec first.')
      if (activeJob?.status === 'succeeded' && activeJobId) {
        const updated = await views.author(view.id, {
          source: activeJob.origin,
          annotations: [],
          proposal_id: activeJobId,
        })
        return { updated, appliedHarnessJobId: activeJobId }
      }
      throw new Error('Create a reviewed proposal before applying this ViewSpec.')
    },
    onSuccess: ({ updated, appliedHarnessJobId }) => finishUpdate(updated, appliedHarnessJobId),
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not apply that view change')),
  })

  const proposeConnection = useMutation({
    mutationFn: () => views.createProposal(view.id, {
      source: 'connection',
      connection_id: connectionId,
      model: model.trim() || undefined,
      instruction: instruction.trim(),
      annotations: annotations.map(({ widget_id, note }) => ({ widget_id, note })),
    }),
    onSuccess: (job) => {
      setSubmittedInstruction(instruction.trim())
      setSubmittedAnnotationCount(annotations.length)
      setActiveJobId(job.id)
      setValidatedCandidate(job.result as ViewCandidate)
      qc.setQueryData(['agent-harness-job', job.id], job)
      qc.setQueryData(['view-open-proposal', view.id], job)
      qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
      if (annotationMode) onToggleAnnotationMode()
      onClearAnnotations()
      toast.success('Connected provider proposal ready for review')
    },
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not generate a reviewed proposal')),
  })

  const queueHarnessJob = useMutation({
    mutationFn: () => views.createHarnessJob(view.id, {
      instruction: instruction.trim(),
      annotations: annotations.map(({ widget_id, note }) => ({ widget_id, note })),
      harness_id: selectedHarnessId,
    }),
    onSuccess: (job) => {
      setSubmittedInstruction(instruction.trim())
      setSubmittedHarnessId(job.requested_harness_id ?? selectedHarnessId)
      setSubmittedAnnotationCount(annotations.length)
      setActiveJobId(job.id)
      setValidatedCandidate(null)
      setCandidateText('')
      qc.setQueryData(['agent-harness-job', job.id], job)
      qc.setQueryData(['view-open-proposal', view.id], job)
      qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
      if (annotationMode) onToggleAnnotationMode()
      onClearAnnotations()
      toast.success(job.status === 'working' ? 'Harness is working' : 'Job queued for the active harness')
    },
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not queue the harness job')),
  })

  const cancelHarnessJob = useMutation({
    mutationFn: () => agentHarness.cancel(activeJobId!),
    onSuccess: (job) => {
      qc.setQueryData(['agent-harness-job', job.id], job)
      qc.setQueryData(['view-open-proposal', view.id], null)
      toast.success('Harness job cancelled')
    },
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not cancel the harness job')),
  })

  const discardProposal = useMutation({
    mutationFn: () => agentHarness.discard(activeJobId!),
    onSuccess: (job) => {
      qc.setQueryData(['agent-harness-job', job.id], job)
      qc.setQueryData(['view-open-proposal', view.id], null)
      qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
      startFreshHarnessRequest()
      toast.success('Proposal discarded; the live view was not changed')
    },
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not discard this proposal')),
  })

  const validateCandidate = useMutation({
    mutationFn: async () => {
      let parsed: unknown
      try {
        parsed = JSON.parse(candidateText)
      } catch {
        throw new Error('The harness output is not valid JSON yet.')
      }
      return views.createProposal(view.id, {
        source: 'import',
        candidate_view: parsed as ViewCandidate,
      })
    },
    onSuccess: (job) => {
      setSource('harness')
      setActiveJobId(job.id)
      setValidatedCandidate(job.result as ViewCandidate)
      qc.setQueryData(['agent-harness-job', job.id], job)
      qc.setQueryData(['view-open-proposal', view.id], job)
      qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
      toast.success('Imported ViewSpec is ready for live review')
    },
    onError: (error: unknown) => {
      setValidatedCandidate(null)
      toast.error(errorDetail(error, 'The candidate ViewSpec did not validate'))
    },
  })

  const copyHarnessBrief = async () => {
    try {
      const grounding = await views.grounding(view.id)
      const brief = {
        task: 'Return one complete revised ViewSpec JSON object. Preserve anything not requested.',
        current_view: {
          name: view.name,
          description: view.description,
          icon: view.icon,
          layout: view.layout,
        },
        whole_view_instruction: instruction.trim(),
        widget_annotations: annotations.map(({ widget_id, note }) => ({ widget_id, note })),
        grounding,
        grounding_contract: [
          'Treat captured campaign IDs and widget query results as authoritative for this workspace.',
          "Campaign metrics require an exact workflow_id; sent counts also require status='sent'.",
          'Never infer delivered messages from send_outcomes.',
        ],
        widget_catalog: catalogQ.data ?? 'Fetch GET /api/views/widgets before authoring.',
        output_contract: {
          name: '1-80 characters',
          description: '0-200 characters',
          icon: 'catalogued icon',
          layout: '1-12 validated widget objects with stable IDs where preserved',
        },
      }
      await navigator.clipboard.writeText(JSON.stringify(brief, null, 2))
      toast.success('Grounded harness brief copied')
    } catch (error: unknown) {
      toast.error(errorDetail(error, 'Could not capture live grounding or write it to the clipboard'))
    }
  }

  const canApplyConnection = Boolean(
    connectionId && !draftLocked && !openProposalQ.isPending &&
    (instruction.trim().length >= 3 || annotations.length > 0),
  )
  const canQueueHarness = Boolean(
    (instruction.trim().length >= 3 || annotations.length > 0) &&
    Boolean(selectedHarnessId) &&
    !openProposalQ.isPending &&
    (!activeJob || TERMINAL_JOB_STATES.has(activeJob.status)),
  )

  const startFreshHarnessRequest = () => {
    if (activeJobId) {
      setDismissedJobIds((current) => new Set(current).add(activeJobId))
    }
    setActiveJobId(null)
    setValidatedCandidate(null)
    setSubmittedInstruction('')
    setSubmittedHarnessId('')
    setSubmittedAnnotationCount(0)
  }

  if (!expanded) {
    const status = activeJob?.status
    const statusLabel = status === 'working'
      ? leaseExpired
        ? 'Harness reconnecting'
        : activelyWorking
          ? `${activeJob?.harness_id ?? 'Harness'} working`
          : 'Harness claimed job'
      : status === 'queued'
        ? 'Harness job queued'
        : status === 'succeeded'
          ? `${activeJob?.origin === 'connection' ? 'Connected API' : activeJob?.origin === 'import' ? 'Imported' : 'Harness'} proposal ready`
          : null
    return (
      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200/80 bg-white/75 px-3 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between dark:border-slate-800 dark:bg-slate-950/55">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-300"><Sparkles size={15} /></span>
          <div className="min-w-0">
            <p className="truncate text-xs font-bold text-slate-800 dark:text-slate-100">Shape this layout with AI</p>
            <p className="truncate text-[10px] text-slate-500">Use a connected API, a live agent harness, or annotate a specific widget.</p>
          </div>
          {statusLabel && (
            <button type="button" onClick={onExpand} className={`ml-1 inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[9px] font-bold ${status === 'succeeded' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : leaseExpired ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300' : 'bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300'}`}>
              {status !== 'succeeded' && <span className={`h-1.5 w-1.5 rounded-full bg-current ${activelyWorking || status === 'queued' ? 'blink' : ''}`} />}{statusLabel}
            </button>
          )}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <Button variant="secondary" size="sm" icon={SlidersHorizontal} onClick={onExpand}>Customize layout</Button>
          <Button
            variant="secondary"
            size="sm"
            icon={MessageSquarePlus}
            onClick={() => {
              if (!annotationMode) onToggleAnnotationMode()
              onExpand()
            }}
          >
            Annotate widgets
          </Button>
        </div>
      </div>
    )
  }

  return (
    <Card padding="sm" className="overflow-hidden border-brand-200 bg-gradient-to-br from-white via-white to-brand-50/80 dark:border-brand-900/60 dark:from-slate-950 dark:via-slate-950 dark:to-brand-950/25">
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-300"><Sparkles size={17} /></span>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-brand-700 dark:text-brand-300">Agent-composable</p>
              <p className="truncate text-sm font-bold text-slate-900 dark:text-white">{label}</p>
              <p className="text-[11px] text-slate-500">Choose who authors the change. Omni validates the same ViewSpec either way.</p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-xl border border-slate-200 bg-slate-100/80 p-1 dark:border-slate-700 dark:bg-slate-900">
              <button
                type="button"
                disabled={draftLocked}
                onClick={() => setSource('connection')}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${source === 'connection' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white' : 'text-slate-500'}`}
              >
                <Cable size={13} /> Connected API
              </button>
              <button
                type="button"
                disabled={draftLocked}
                onClick={() => setSource('harness')}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${source === 'harness' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white' : 'text-slate-500'}`}
              >
                <Bot size={13} /> Agent harness
              </button>
            </div>
            <button
              type="button"
              disabled={draftLocked}
              onClick={onToggleAnnotationMode}
              aria-pressed={annotationMode}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[11px] font-bold transition disabled:cursor-not-allowed disabled:opacity-50 ${annotationMode ? 'border-brand-400 bg-brand-600 text-white shadow-sm' : 'border-brand-200 bg-white text-brand-700 hover:border-brand-400 dark:border-brand-900 dark:bg-slate-900 dark:text-brand-300'}`}
            >
              <MessageSquarePlus size={14} /> {annotationMode ? 'Annotation mode on' : 'Annotate widgets'}
              {annotations.length > 0 && <span className="rounded-full bg-white/90 px-1.5 py-0.5 text-[9px] text-brand-700">{annotations.length}</span>}
            </button>
            <button type="button" onClick={onClose} aria-label="Close layout customizer" className="grid h-9 w-9 place-items-center rounded-xl border border-slate-200 bg-white text-slate-500 transition hover:border-slate-300 hover:text-slate-800 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400 dark:hover:text-white"><X size={14} /></button>
          </div>
        </div>

        {annotations.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-brand-200 bg-brand-50/80 px-3 py-2 text-[11px] text-brand-900 dark:border-brand-900 dark:bg-brand-950/30 dark:text-brand-100">
            <span><strong>{annotations.length} widget annotation{annotations.length === 1 ? '' : 's'} queued.</strong> They stay attached to their widget IDs until this change is applied.</span>
            <button type="button" onClick={onClearAnnotations} className="font-bold text-brand-700 hover:underline dark:text-brand-300">Clear all</button>
          </div>
        )}

        {source === 'connection' ? (
          <div className="space-y-3 rounded-2xl border border-slate-200 bg-white/85 p-3 dark:border-slate-800 dark:bg-slate-950/55">
            {connections.length > 0 ? (
              <div className="grid gap-2 lg:grid-cols-[minmax(220px,.8fr)_minmax(180px,.55fr)]">
                <label className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
                  AI connection
                  <select value={connectionId} disabled={draftLocked} onChange={(event) => setConnectionId(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-800 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800">
                    {connections.map((connection) => <option key={connection.id} value={connection.id}>{providerLabel(connection)}</option>)}
                  </select>
                </label>
                <label className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
                  Model
                  <input value={model} disabled={draftLocked} onChange={(event) => setModel(event.target.value)} placeholder="Model ID" className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-800 outline-none focus:border-brand-400 disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-800" />
                </label>
              </div>
            ) : (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                No supported AI authoring connection is configured. Connect Anthropic, OpenAI, OpenRouter, Gemini, or an OpenAI-compatible API in <a href="/integrations" className="font-bold underline">Integrations</a>.
              </div>
            )}
            <textarea value={draftLocked ? submittedInstruction : instruction} disabled={draftLocked} onChange={(event) => setInstruction(event.target.value)} rows={2} placeholder={draftLocked ? 'This instruction is frozen with the proposal below.' : placeholder} className="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm leading-6 text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 disabled:cursor-not-allowed disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:disabled:bg-slate-800 dark:focus:ring-brand-950" />
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              {suggestions.length > 0 && (
                <div className="flex min-w-0 flex-wrap gap-1.5">
                  {suggestions.map((suggestion) => (
                    <button key={suggestion} type="button" disabled={draftLocked} onClick={() => setInstruction(suggestion)} className="max-w-[310px] truncate rounded-full border border-slate-200 bg-white/80 px-2.5 py-1 text-[11px] text-slate-500 transition hover:border-brand-300 hover:text-brand-700 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400" title={suggestion}>{suggestion}</button>
                  ))}
                </div>
              )}
              <Button className="shrink-0" icon={Sparkles} isLoading={proposeConnection.isPending} disabled={!canApplyConnection || proposeConnection.isPending} onClick={() => proposeConnection.mutate()}>
                {proposeConnection.isPending ? 'Composing…' : annotations.length > 0 ? `Review ${annotations.length} annotation${annotations.length === 1 ? '' : 's'}` : 'Generate proposal'}
              </Button>
            </div>
            {activeJob?.status === 'succeeded' && validatedCandidate && (
              <>
                <ProposalReview
                  job={activeJob}
                  candidate={validatedCandidate}
                  isApplying={apply.isPending}
                  onApply={() => apply.mutate()}
                  onStartFresh={() => discardProposal.mutate()}
                />
                {discardProposal.isPending && <p className="text-[10px] text-slate-500">Discarding proposal…</p>}
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3 rounded-2xl border border-violet-200 bg-white/90 p-3 dark:border-violet-900/60 dark:bg-slate-950/60">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,.78fr)_minmax(0,1.22fr)]">
              <div className="space-y-3 rounded-xl bg-violet-50/70 p-3 dark:bg-violet-950/25">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="flex items-center gap-1.5 text-xs font-bold text-violet-900 dark:text-violet-100"><Radio size={14} /> Live harness</p>
                    <p className="mt-1 text-[11px] leading-relaxed text-violet-700 dark:text-violet-300">Codex, Claude Code, or OpenCode holds a workspace poll and claims one grounded job at a time.</p>
                  </div>
                  <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${workers.length > 0 ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : !presenceAvailable ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${workers.length > 0 ? 'bg-emerald-500 ring-pulse' : !presenceAvailable ? 'bg-amber-500' : 'bg-slate-400'}`} />
                    {workers.length > 0 ? `${workers.length} online` : presenceAvailable ? 'offline' : 'status unavailable'}
                  </span>
                </div>

                {draftLocked ? (
                  <div className="rounded-xl border border-violet-200 bg-white/80 px-3 py-2.5 dark:border-violet-900 dark:bg-slate-950/45">
                    <p className="text-[9px] font-bold uppercase tracking-[0.1em] text-violet-700 dark:text-violet-300">Submitted runner</p>
                    <p className="mt-1 truncate font-mono text-[10px] font-semibold text-slate-700 dark:text-slate-200">{submittedHarnessId || activeJob?.requested_harness_id || activeJob?.harness_id || 'Assigned harness'}</p>
                  </div>
                ) : workers.length > 0 ? (
                  <label className="block text-[9px] font-bold uppercase tracking-[0.1em] text-violet-700 dark:text-violet-300">
                    Run with
                    <select value={selectedHarnessId} onChange={(event) => setSelectedHarnessId(event.target.value)} className="mt-1 w-full rounded-lg border border-violet-200 bg-white px-2.5 py-2 font-mono text-[10px] font-semibold normal-case tracking-normal text-slate-700 outline-none focus:border-violet-400 dark:border-violet-900 dark:bg-slate-950 dark:text-slate-200">
                      {workers.map((worker) => (
                        <option key={worker.harness_id} value={worker.harness_id}>{worker.harness_id} · {worker.state}</option>
                      ))}
                    </select>
                  </label>
                ) : !presenceAvailable ? (
                  <div className="rounded-xl border border-dashed border-amber-300 bg-amber-50/70 p-2.5 text-[10px] leading-relaxed text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
                    <p className="flex items-center gap-1.5 font-bold"><AlertTriangle size={12} /> Harness presence cannot be observed</p>
                    <p className="mt-1.5">Durable jobs remain safe, but Omni cannot currently say whether a runner is polling. Retry after Redis presence recovers.</p>
                  </div>
                ) : (
                  <div className="rounded-xl border border-dashed border-violet-300 bg-white/70 p-2.5 text-[10px] leading-relaxed text-violet-700 dark:border-violet-800 dark:bg-slate-950/40 dark:text-violet-300">
                    <p className="flex items-center gap-1.5 font-bold"><Terminal size={12} /> No harness is polling yet</p>
                    <code className="mt-1.5 block overflow-x-auto rounded-lg bg-slate-950 px-2 py-1.5 font-mono text-[9px] text-emerald-300">python scripts/omni_harness.py run --engine codex --codex-session-mode resumable</code>
                    <p className="mt-1.5">Set <code>OMNI_API_URL</code> and <code>OMNI_API_KEY</code> locally. The key is never shown in Omni or returned in a job.</p>
                  </div>
                )}

                <textarea
                  value={draftLocked ? submittedInstruction : instruction}
                  onChange={(event) => setInstruction(event.target.value)}
                  rows={4}
                  disabled={draftLocked}
                  placeholder={draftLocked ? 'The submitted instruction is frozen with this job.' : 'What should the harness change across this view? Widget annotations are added automatically…'}
                  className="w-full resize-y rounded-xl border border-violet-200 bg-white px-3 py-2 text-xs leading-relaxed text-slate-800 outline-none focus:border-violet-400 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500 dark:border-violet-900 dark:bg-slate-950 dark:text-slate-100 dark:disabled:bg-slate-900"
                />
                {draftLocked && (
                  <p className="text-[10px] leading-relaxed text-violet-700 dark:text-violet-300">
                    This request is frozen in job <span className="font-mono font-semibold">{activeJob?.id.slice(0, 8)}</span>{submittedAnnotationCount > 0 ? ` with ${submittedAnnotationCount} widget note${submittedAnnotationCount === 1 ? '' : 's'}` : ''}. Changes made now would not affect that job.
                  </p>
                )}
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" icon={Bot} isLoading={queueHarnessJob.isPending} disabled={draftLocked || !canQueueHarness || queueHarnessJob.isPending} onClick={() => queueHarnessJob.mutate()}>
                    {draftLocked ? 'Request submitted' : queueHarnessJob.isPending ? 'Queuing…' : 'Send to harness'}
                  </Button>
                  <Button variant="secondary" size="sm" icon={Copy} onClick={copyHarnessBrief} disabled={draftLocked || catalogQ.isLoading}>Copy grounded brief</Button>
                </div>
                <p className="text-[10px] leading-relaxed text-violet-600 dark:text-violet-400">The job contains the current ViewSpec, live RLS-scoped widget results, authoritative campaign IDs/status counts, and the widget catalog—not provider credentials. It cannot publish actions or touch campaign execution.</p>
              </div>

              <div className="min-h-[250px] rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/45">
                {!activeJob ? (
                  <div className="grid h-full min-h-[220px] place-items-center text-center">
                    <div className="max-w-sm">
                      <span className="mx-auto grid h-11 w-11 place-items-center rounded-2xl bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-300"><Bot size={19} /></span>
                      <p className="mt-3 text-sm font-bold text-slate-800 dark:text-slate-100">No view job queued</p>
                      <p className="mt-1 text-[11px] leading-relaxed text-slate-500">Write a whole-view instruction or annotate individual widgets, then send one grounded job to the continuously polling runner.</p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-200 pb-3 dark:border-slate-800">
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">Live job</p>
                        <p className="mt-0.5 font-mono text-[11px] font-semibold text-slate-700 dark:text-slate-200">{activeJob.id}</p>
                        <p className="mt-1 text-[9px] text-slate-400">Based on view revision {shortTime(activeJob.target_version)}</p>
                      </div>
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${activeJob.status === 'succeeded' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : leaseExpired ? 'bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300' : activeJob.status === 'working' ? 'bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300' : activeJob.status === 'queued' ? 'bg-sky-100 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300' : 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300'}`}>
                        {(activeJob.status === 'queued' || activelyWorking) && <span className="h-1.5 w-1.5 rounded-full bg-current blink" />}
                        {leaseExpired ? 'reconnecting' : activelyWorking ? 'working' : activeJob.status === 'working' ? 'claimed' : activeJob.status}
                      </span>
                    </div>

                    {activeJob.status === 'queued' && (
                      <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-800 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-200">
                        <p className="flex items-center gap-1.5 font-bold"><Radio size={13} className="ring-pulse" /> Waiting for the next harness poll</p>
                        <p className="mt-1 text-[10px] leading-relaxed opacity-80">The job is durable. It remains queued across browser refreshes and harness reconnects.</p>
                      </div>
                    )}

                    {activelyWorking && (
                      <div className="rounded-xl border border-violet-200 bg-violet-50 p-3 text-xs text-violet-900 dark:border-violet-900 dark:bg-violet-950/30 dark:text-violet-100">
                        <p className="flex items-center gap-1.5 font-bold"><Activity size={13} className="blink" /> {activeJob.harness_id ?? 'Harness'} is actively working</p>
                        <p className="mt-1 text-[10px] leading-relaxed text-violet-700 dark:text-violet-300">Lease attempt {activeJob.attempts}. Last verified heartbeat {shortTime(activeJob.last_heartbeat_at)}.</p>
                      </div>
                    )}

                    {activeJob.status === 'working' && !activelyWorking && leaseExpired && (
                      <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                        <p className="flex items-center gap-1.5 font-bold"><RefreshCw size={13} /> Worker disconnected; waiting for lease recovery</p>
                        <p className="mt-1 text-[10px] leading-relaxed text-amber-800 dark:text-amber-300">The last lease expired after the heartbeat at {shortTime(activeJob.last_heartbeat_at)}. Omni will return this job to the queue; it is not currently reporting active work.</p>
                      </div>
                    )}

                    {activeJob.status === 'working' && !activelyWorking && !leaseExpired && (
                      <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-900 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-100">
                        <p className="flex items-center gap-1.5 font-bold"><Radio size={13} /> Job claimed; waiting for a verified heartbeat</p>
                        <p className="mt-1 text-[10px] leading-relaxed text-sky-700 dark:text-sky-300">Omni has assigned the lease, but the live presence poll has not yet confirmed active execution.</p>
                      </div>
                    )}

                    {activeJob.progress.length > 0 && (
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">Progress</p>
                        <div className="mt-1.5 space-y-1.5">
                          {activeJob.progress.slice(-5).map((event, index) => (
                            <div key={`${event.at}-${index}`} className="flex gap-2 rounded-lg bg-white px-2.5 py-2 text-[10px] text-slate-600 shadow-sm dark:bg-slate-900 dark:text-slate-300">
                              <Activity size={11} className="mt-0.5 shrink-0 text-violet-500" />
                              <span className="min-w-0 flex-1">{event.message}</span>
                              <time className="shrink-0 text-[9px] text-slate-400">{shortTime(event.at)}</time>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {activeJob.status === 'succeeded' && validatedCandidate && (
                      <ProposalReview
                        job={activeJob}
                        candidate={validatedCandidate}
                        isApplying={apply.isPending}
                        onApply={() => apply.mutate()}
                        onStartFresh={() => discardProposal.mutate()}
                      />
                    )}

                    {(['failed', 'cancelled', 'expired'] as const).includes(activeJob.status as 'failed' | 'cancelled' | 'expired') && (
                      <div className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">
                        <p className="font-bold">Job {activeJob.status}</p>
                        <p className="mt-1 text-[10px] leading-relaxed">{activeJob.error || 'No candidate was applied. Adjust the instruction and queue a fresh job.'}</p>
                      </div>
                    )}

                    {(activeJob.status === 'queued' || activeJob.status === 'working') && (
                      <button type="button" onClick={() => cancelHarnessJob.mutate()} disabled={cancelHarnessJob.isPending} className="inline-flex items-center gap-1 text-[10px] font-bold text-slate-500 hover:text-rose-600 disabled:opacity-50"><X size={11} /> Cancel job</button>
                    )}
                  </div>
                )}
              </div>
            </div>

            <details className="rounded-xl border border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-950/35">
              <summary className="cursor-pointer px-3 py-2 text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">Advanced recovery · import a ViewSpec manually</summary>
              <div className="space-y-3 border-t border-slate-200 p-3 dark:border-slate-800">
                <textarea
                  value={candidateText}
                  onChange={(event) => { setCandidateText(event.target.value); setValidatedCandidate(null) }}
                  rows={7}
                  spellCheck={false}
                  placeholder={'{\n  "name": "Overview",\n  "description": "…",\n  "icon": "layout-dashboard",\n  "layout": […]\n}'}
                  className="w-full resize-y rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 font-mono text-[11px] leading-relaxed text-emerald-200 outline-none focus:border-violet-400"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="secondary" size="sm" icon={Braces} isLoading={validateCandidate.isPending} disabled={candidateText.trim().length < 2 || validateCandidate.isPending || draftLocked || openProposalQ.isPending} onClick={() => validateCandidate.mutate()}>Review imported ViewSpec</Button>
                </div>
              </div>
            </details>
          </div>
        )}
      </div>
    </Card>
  )
}
