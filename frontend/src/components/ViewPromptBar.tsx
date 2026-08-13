import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, Bot, Braces, Cable, Check, Copy, MessageSquarePlus, Radio, SlidersHorizontal, Sparkles, Terminal, Upload, X } from 'lucide-react'
import {
  agentHarness,
  views,
  type AgentHarnessJob,
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
    queryKey: ['agent-harness-workers'],
    queryFn: agentHarness.workers,
    enabled: source === 'harness',
    refetchInterval: source === 'harness' ? 2_000 : false,
  })
  const recentJobsQ = useQuery({
    queryKey: ['agent-harness-jobs'],
    queryFn: agentHarness.jobs,
    enabled: source === 'harness' && !activeJobId,
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
  const workers = useMemo(() => workersQ.data ?? [], [workersQ.data])
  const activeJob = jobQ.data
  const selectedConnection = connections.find((connection) => connection.id === connectionId)

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
    const recoverable = recentJobsQ.data?.find((job) =>
      job.kind === 'view.author' &&
      job.target_type === 'view' &&
      job.target_id === view.id &&
      !job.applied_at &&
      ['queued', 'working', 'succeeded'].includes(job.status),
    )
    if (recoverable) setActiveJobId(recoverable.id)
  }, [activeJobId, recentJobsQ.data, view.id])

  const finishUpdate = (updated: ViewDef) => {
    qc.setQueryData(['view', view.id], updated)
    qc.setQueryData<ViewDef | undefined>(['default-view'], (current) => current?.id === updated.id ? updated : current)
    qc.invalidateQueries({ queryKey: ['view-widget'] })
    qc.invalidateQueries({ queryKey: ['views'] })
    setInstruction('')
    setCandidateText('')
    setValidatedCandidate(null)
    if (activeJobId) {
      qc.setQueryData<AgentHarnessJob[]>(['agent-harness-jobs'], (jobs) =>
        jobs?.map((job) => job.id === activeJobId ? { ...job, applied_at: new Date().toISOString() } : job),
      )
    }
    setActiveJobId(null)
    qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
    onClearAnnotations()
    onUpdated?.(updated)
    toast.success('View updated')
  }

  const apply = useMutation({
    mutationFn: () => {
      const groundedAnnotations = annotations.map(({ widget_id, note }) => ({ widget_id, note }))
      if (source === 'connection') {
        return views.author(view.id, {
          source: 'connection',
          connection_id: connectionId,
          model: model.trim() || undefined,
          instruction: instruction.trim(),
          annotations: groundedAnnotations,
        })
      }
      if (!validatedCandidate) throw new Error('Validate the agent-authored ViewSpec first.')
      if (activeJob?.status === 'succeeded' && activeJobId) {
        return views.author(view.id, {
          source: 'harness',
          instruction: instruction.trim(),
          annotations: groundedAnnotations,
          harness_job_id: activeJobId,
        })
      }
      return views.author(view.id, {
        source: 'harness',
        instruction: instruction.trim(),
        annotations: groundedAnnotations,
        candidate_view: validatedCandidate,
      })
    },
    onSuccess: finishUpdate,
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not apply that view change')),
  })

  const queueHarnessJob = useMutation({
    mutationFn: () => views.createHarnessJob(view.id, {
      instruction: instruction.trim(),
      annotations: annotations.map(({ widget_id, note }) => ({ widget_id, note })),
      harness_id: selectedHarnessId,
    }),
    onSuccess: (job) => {
      setActiveJobId(job.id)
      setValidatedCandidate(null)
      setCandidateText('')
      qc.setQueryData(['agent-harness-job', job.id], job)
      qc.invalidateQueries({ queryKey: ['agent-harness-jobs'] })
      toast.success(job.status === 'working' ? 'Harness is working' : 'Job queued for the active harness')
    },
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not queue the harness job')),
  })

  const cancelHarnessJob = useMutation({
    mutationFn: () => agentHarness.cancel(activeJobId!),
    onSuccess: (job) => {
      qc.setQueryData(['agent-harness-job', job.id], job)
      toast.success('Harness job cancelled')
    },
    onError: (error: unknown) => toast.error(errorDetail(error, 'Could not cancel the harness job')),
  })

  const validateCandidate = useMutation({
    mutationFn: async () => {
      let parsed: unknown
      try {
        parsed = JSON.parse(candidateText)
      } catch {
        throw new Error('The harness output is not valid JSON yet.')
      }
      return views.validateCandidate(parsed as ViewCandidate)
    },
    onSuccess: (candidate) => {
      setActiveJobId(null)
      setValidatedCandidate(candidate)
      toast.success('ViewSpec validated — review the summary, then apply')
    },
    onError: (error: unknown) => {
      setValidatedCandidate(null)
      toast.error(errorDetail(error, 'The candidate ViewSpec did not validate'))
    },
  })

  const copyHarnessBrief = async () => {
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
      widget_catalog: catalogQ.data ?? 'Fetch GET /api/views/widgets before authoring.',
      output_contract: {
        name: '1-80 characters',
        description: '0-200 characters',
        icon: 'catalogued icon',
        layout: '1-12 validated widget objects with stable IDs where preserved',
      },
    }
    try {
      await navigator.clipboard.writeText(JSON.stringify(brief, null, 2))
      toast.success('Grounded harness brief copied')
    } catch {
      toast.error('Clipboard access failed. Copy the brief from a browser that allows clipboard access.')
    }
  }

  const canApplyConnection = Boolean(
    connectionId && (instruction.trim().length >= 3 || annotations.length > 0),
  )
  const canQueueHarness = Boolean(
    (instruction.trim().length >= 3 || annotations.length > 0) &&
    Boolean(selectedHarnessId) &&
    (!activeJob || TERMINAL_JOB_STATES.has(activeJob.status)),
  )

  if (!expanded) {
    const status = activeJob?.status
    const statusLabel = status === 'working'
      ? `${activeJob?.harness_id ?? 'Harness'} working`
      : status === 'queued'
        ? 'Harness job queued'
        : status === 'succeeded'
          ? 'Harness result ready'
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
            <button type="button" onClick={onExpand} className={`ml-1 inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[9px] font-bold ${status === 'succeeded' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : 'bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300'}`}>
              {status !== 'succeeded' && <span className="h-1.5 w-1.5 rounded-full bg-current blink" />}{statusLabel}
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
                onClick={() => setSource('connection')}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold transition ${source === 'connection' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white' : 'text-slate-500'}`}
              >
                <Cable size={13} /> Connected API
              </button>
              <button
                type="button"
                onClick={() => setSource('harness')}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-bold transition ${source === 'harness' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-800 dark:text-white' : 'text-slate-500'}`}
              >
                <Bot size={13} /> Agent harness
              </button>
            </div>
            <button
              type="button"
              onClick={onToggleAnnotationMode}
              aria-pressed={annotationMode}
              className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-2 text-[11px] font-bold transition ${annotationMode ? 'border-brand-400 bg-brand-600 text-white shadow-sm' : 'border-brand-200 bg-white text-brand-700 hover:border-brand-400 dark:border-brand-900 dark:bg-slate-900 dark:text-brand-300'}`}
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
                  <select value={connectionId} onChange={(event) => setConnectionId(event.target.value)} className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-800 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100">
                    {connections.map((connection) => <option key={connection.id} value={connection.id}>{providerLabel(connection)}</option>)}
                  </select>
                </label>
                <label className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
                  Model
                  <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="Model ID" className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm font-normal normal-case tracking-normal text-slate-800 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100" />
                </label>
              </div>
            ) : (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-300">
                No supported AI authoring connection is configured. Connect Anthropic, OpenAI, OpenRouter, Gemini, or an OpenAI-compatible API in <a href="/integrations" className="font-bold underline">Integrations</a>.
              </div>
            )}
            <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={2} placeholder={placeholder} className="w-full resize-y rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm leading-6 text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-brand-950" />
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              {suggestions.length > 0 && (
                <div className="flex min-w-0 flex-wrap gap-1.5">
                  {suggestions.map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => setInstruction(suggestion)} className="max-w-[310px] truncate rounded-full border border-slate-200 bg-white/80 px-2.5 py-1 text-[11px] text-slate-500 transition hover:border-brand-300 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400" title={suggestion}>{suggestion}</button>
                  ))}
                </div>
              )}
              <Button className="shrink-0" icon={Sparkles} isLoading={apply.isPending} disabled={!canApplyConnection || apply.isPending} onClick={() => apply.mutate()}>
                {apply.isPending ? 'Composing…' : annotations.length > 0 ? `Apply ${annotations.length} annotation${annotations.length === 1 ? '' : 's'}` : 'Apply view'}
              </Button>
            </div>
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
                  <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${workers.length > 0 ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : 'bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300'}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${workers.length > 0 ? 'bg-emerald-500 ring-pulse' : 'bg-slate-400'}`} />
                    {workers.length > 0 ? `${workers.length} active` : 'offline'}
                  </span>
                </div>

                {workers.length > 0 ? (
                  <label className="block text-[9px] font-bold uppercase tracking-[0.1em] text-violet-700 dark:text-violet-300">
                    Run with
                    <select value={selectedHarnessId} onChange={(event) => setSelectedHarnessId(event.target.value)} className="mt-1 w-full rounded-lg border border-violet-200 bg-white px-2.5 py-2 font-mono text-[10px] font-semibold normal-case tracking-normal text-slate-700 outline-none focus:border-violet-400 dark:border-violet-900 dark:bg-slate-950 dark:text-slate-200">
                      {workers.map((worker) => (
                        <option key={worker.harness_id} value={worker.harness_id}>{worker.harness_id} · {worker.state}</option>
                      ))}
                    </select>
                  </label>
                ) : (
                  <div className="rounded-xl border border-dashed border-violet-300 bg-white/70 p-2.5 text-[10px] leading-relaxed text-violet-700 dark:border-violet-800 dark:bg-slate-950/40 dark:text-violet-300">
                    <p className="flex items-center gap-1.5 font-bold"><Terminal size={12} /> No harness is polling yet</p>
                    <code className="mt-1.5 block overflow-x-auto rounded-lg bg-slate-950 px-2 py-1.5 font-mono text-[9px] text-emerald-300">python scripts/omni_harness.py run --engine codex</code>
                    <p className="mt-1.5">Set <code>OMNI_API_URL</code> and <code>OMNI_API_KEY</code> locally. The key is never shown in Omni or returned in a job.</p>
                  </div>
                )}

                <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={4} placeholder="What should the harness change across this view? Widget annotations are added automatically…" className="w-full resize-y rounded-xl border border-violet-200 bg-white px-3 py-2 text-xs leading-relaxed text-slate-800 outline-none focus:border-violet-400 dark:border-violet-900 dark:bg-slate-950 dark:text-slate-100" />
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" icon={Bot} isLoading={queueHarnessJob.isPending} disabled={!canQueueHarness || queueHarnessJob.isPending} onClick={() => queueHarnessJob.mutate()}>
                    {queueHarnessJob.isPending ? 'Queuing…' : 'Send to harness'}
                  </Button>
                  <Button variant="secondary" size="sm" icon={Copy} onClick={copyHarnessBrief} disabled={catalogQ.isLoading}>Copy grounded brief</Button>
                </div>
                <p className="text-[10px] leading-relaxed text-violet-600 dark:text-violet-400">The job contains the current ViewSpec and widget catalog—not provider credentials. It cannot publish actions or touch campaign execution.</p>
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
                      </div>
                      <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold ${activeJob.status === 'succeeded' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : activeJob.status === 'working' ? 'bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300' : activeJob.status === 'queued' ? 'bg-sky-100 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300' : 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300'}`}>
                        {(activeJob.status === 'queued' || activeJob.status === 'working') && <span className="h-1.5 w-1.5 rounded-full bg-current blink" />}
                        {activeJob.status}
                      </span>
                    </div>

                    {activeJob.status === 'queued' && (
                      <div className="rounded-xl border border-sky-200 bg-sky-50 p-3 text-xs text-sky-800 dark:border-sky-900 dark:bg-sky-950/30 dark:text-sky-200">
                        <p className="flex items-center gap-1.5 font-bold"><Radio size={13} className="ring-pulse" /> Waiting for the next harness poll</p>
                        <p className="mt-1 text-[10px] leading-relaxed opacity-80">The job is durable. It remains queued across browser refreshes and harness reconnects.</p>
                      </div>
                    )}

                    {activeJob.status === 'working' && (
                      <div className="rounded-xl border border-violet-200 bg-violet-50 p-3 text-xs text-violet-900 dark:border-violet-900 dark:bg-violet-950/30 dark:text-violet-100">
                        <p className="flex items-center gap-1.5 font-bold"><Activity size={13} className="blink" /> {activeJob.harness_id ?? 'Harness'} is actively working</p>
                        <p className="mt-1 text-[10px] leading-relaxed text-violet-700 dark:text-violet-300">Lease attempt {activeJob.attempts}. Heartbeats keep ownership live; an abandoned lease returns safely to the queue.</p>
                      </div>
                    )}

                    {activeJob.progress.length > 0 && (
                      <div>
                        <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">Progress</p>
                        <div className="mt-1.5 space-y-1.5">
                          {activeJob.progress.slice(-5).map((event, index) => (
                            <div key={`${event.at}-${index}`} className="flex gap-2 rounded-lg bg-white px-2.5 py-2 text-[10px] text-slate-600 shadow-sm dark:bg-slate-900 dark:text-slate-300">
                              <Check size={11} className="mt-0.5 shrink-0 text-violet-500" />
                              <span>{event.message}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {activeJob.status === 'succeeded' && validatedCandidate && (
                      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950/30">
                        <p className="flex items-center gap-1.5 text-xs font-bold text-emerald-800 dark:text-emerald-200"><Check size={13} /> Validated candidate ready</p>
                        <p className="mt-1 text-[10px] leading-relaxed text-emerald-700 dark:text-emerald-300"><strong>{validatedCandidate.name}</strong> · {validatedCandidate.layout.length} widgets. Review is complete; nothing has been applied yet.</p>
                        <Button className="mt-3" size="sm" icon={Upload} isLoading={apply.isPending} disabled={apply.isPending} onClick={() => apply.mutate()}>Apply harness result</Button>
                      </div>
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
                  <Button variant="secondary" size="sm" icon={Braces} isLoading={validateCandidate.isPending} disabled={candidateText.trim().length < 2 || validateCandidate.isPending} onClick={() => validateCandidate.mutate()}>Validate imported ViewSpec</Button>
                  {validatedCandidate && !activeJobId && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"><Check size={11} /> {validatedCandidate.layout.length} widgets valid</span>}
                  <Button className="ml-auto" size="sm" icon={Upload} isLoading={apply.isPending} disabled={!validatedCandidate || Boolean(activeJobId) || apply.isPending} onClick={() => apply.mutate()}>Apply imported view</Button>
                </div>
              </div>
            </details>
          </div>
        )}
      </div>
    </Card>
  )
}
