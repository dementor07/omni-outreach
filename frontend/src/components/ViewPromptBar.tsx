import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bot, Braces, Cable, Check, Copy, MessageSquarePlus, Sparkles, Upload } from 'lucide-react'
import {
  views,
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
}

type AuthoringSource = 'connection' | 'harness'

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
}: Props) {
  const qc = useQueryClient()
  const toast = useToast()
  const [source, setSource] = useState<AuthoringSource>('connection')
  const [instruction, setInstruction] = useState('')
  const [connectionId, setConnectionId] = useState('')
  const [model, setModel] = useState('')
  const [candidateText, setCandidateText] = useState('')
  const [validatedCandidate, setValidatedCandidate] = useState<ViewCandidate | null>(null)

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
  const connections = useMemo(() => connectionsQ.data ?? [], [connectionsQ.data])
  const selectedConnection = connections.find((connection) => connection.id === connectionId)

  useEffect(() => {
    if (connections.length === 0) return
    const selected = connections.find((connection) => connection.id === connectionId) ?? connections[0]
    if (selected.id !== connectionId) setConnectionId(selected.id)
  }, [connectionId, connections])

  useEffect(() => {
    if (selectedConnection?.default_model) setModel(selectedConnection.default_model)
  }, [selectedConnection?.id, selectedConnection?.default_model])

  const finishUpdate = (updated: ViewDef) => {
    qc.setQueryData(['view', view.id], updated)
    qc.setQueryData(['default-view'], updated)
    qc.invalidateQueries({ queryKey: ['view-widget'] })
    qc.invalidateQueries({ queryKey: ['views'] })
    setInstruction('')
    setCandidateText('')
    setValidatedCandidate(null)
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
          <div className="grid gap-3 rounded-2xl border border-violet-200 bg-white/90 p-3 dark:border-violet-900/60 dark:bg-slate-950/60 lg:grid-cols-[minmax(0,.75fr)_minmax(0,1.25fr)]">
            <div className="space-y-3 rounded-xl bg-violet-50/70 p-3 dark:bg-violet-950/25">
              <div>
                <p className="flex items-center gap-1.5 text-xs font-bold text-violet-900 dark:text-violet-100"><Bot size={14} /> Grounded agent brief</p>
                <p className="mt-1 text-[11px] leading-relaxed text-violet-700 dark:text-violet-300">Exports the current ViewSpec, catalog, whole-view instruction, and every widget annotation. Use it in Codex, Claude Code, or another harness.</p>
              </div>
              <textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} rows={3} placeholder="Optional whole-view instruction for the harness…" className="w-full resize-y rounded-xl border border-violet-200 bg-white px-3 py-2 text-xs leading-relaxed text-slate-800 outline-none focus:border-violet-400 dark:border-violet-900 dark:bg-slate-950 dark:text-slate-100" />
              <Button variant="secondary" size="sm" icon={Copy} onClick={copyHarnessBrief} disabled={catalogQ.isLoading}>Copy grounded brief</Button>
              <p className="text-[10px] leading-relaxed text-violet-600 dark:text-violet-400">The harness does not receive credentials and cannot bypass Omni’s query or widget validators.</p>
            </div>
            <div className="space-y-3">
              <label className="block text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
                Complete ViewSpec returned by the harness
                <textarea
                  value={candidateText}
                  onChange={(event) => { setCandidateText(event.target.value); setValidatedCandidate(null) }}
                  rows={8}
                  spellCheck={false}
                  placeholder={'{\n  "name": "Overview",\n  "description": "…",\n  "icon": "layout-dashboard",\n  "layout": […]\n}'}
                  className="mt-1 w-full resize-y rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 font-mono text-[11px] font-normal normal-case leading-relaxed tracking-normal text-emerald-200 outline-none focus:border-violet-400"
                />
              </label>
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" size="sm" icon={Braces} isLoading={validateCandidate.isPending} disabled={candidateText.trim().length < 2 || validateCandidate.isPending} onClick={() => validateCandidate.mutate()}>Validate ViewSpec</Button>
                {validatedCandidate && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-bold text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"><Check size={11} /> {validatedCandidate.layout.length} widgets valid</span>
                )}
                <Button className="ml-auto" size="sm" icon={Upload} isLoading={apply.isPending} disabled={!validatedCandidate || apply.isPending} onClick={() => apply.mutate()}>Apply imported view</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}
