import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { X, GitBranch, DollarSign, Clock, ExternalLink, Loader2, CornerDownRight, ArrowUp } from 'lucide-react'
import { clsx } from 'clsx'
import { projections, type LineageLead } from '../api/v2'
import { nodeLabel } from '../utils/nodeLabel'
import Badge from './Badge'
import { timeAgo } from '../lib/format'

// The Leads list answers "what leads exist"; this drawer answers "what happened
// to THIS one, and why is it here". It reconstructs the lead's distributed run
// from the event archive (GET /projections/leads/{id}/journey): a vertical
// timeline of node events, the fan-out lineage (parent company ↔ child people),
// the AI cost it incurred, and a plain-English status reason. Clicking a lineage
// lead swaps the drawer to that lead — so you can walk a company down to its
// people without leaving the panel.

const TERMINAL = new Set(['completed', 'errored', 'cancelled', 'converted', 'ended', 'suppressed'])

interface LeadDrawerProps {
  leadId: string
  onClose: () => void
  onSelectLead: (id: string) => void
}

export default function LeadDrawer({ leadId, onClose, onSelectLead }: LeadDrawerProps) {
  const q = useQuery({
    queryKey: ['lead-journey', leadId],
    queryFn: () => projections.leadJourney(leadId),
    // Poll while the lead is still in flight so the timeline grows live.
    refetchInterval: (query) => (query.state.data && !TERMINAL.has(query.state.data.lead.status) ? 6000 : false),
  })

  // Escape closes the drawer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const j = q.data
  const linkedin = j ? (j.lead.fields.linkedin_url as string | undefined) || (j.lead.custom_fields.linkedin_url as string | undefined) : undefined

  return createPortal(
    <div className="fixed inset-0 z-[70] flex justify-end">
      {/* Scrim */}
      <button
        type="button"
        aria-label="Close lead detail"
        onClick={onClose}
        className="absolute inset-0 bg-slate-900/40 backdrop-blur-[1px] animate-in fade-in"
      />
      {/* Panel */}
      <aside className="glass-panel relative flex h-full w-full max-w-md flex-col animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-brand-500">Lead detail</p>
            <p className="truncate text-lg font-bold text-slate-900 dark:text-white">{j?.lead.identity ?? '…'}</p>
            {j && (
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge label={j.lead.status} asStatus dot size="sm" />
                <Badge label={j.lead.stage} variant="neutral" size="sm" />
                <span className="font-mono text-[10px] text-slate-400">{j.lead.id.slice(0, 8)}</span>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
          >
            <X size={18} />
          </button>
        </div>

        {q.isLoading ? (
          <div className="flex flex-1 items-center justify-center text-slate-400">
            <Loader2 className="animate-spin" size={20} />
          </div>
        ) : !j ? (
          <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-slate-500">
            Could not load this lead's journey.
          </div>
        ) : (
          <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
            {/* Why is it here */}
            <div className="rounded-xl bg-slate-50 p-3.5 dark:bg-slate-800/50">
              <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Status</p>
              <p className="mt-1 text-[13px] leading-relaxed text-slate-700 dark:text-slate-200">{j.status_reason}</p>
            </div>

            {/* Lineage */}
            {(j.parent || j.children.length > 0) && (
              <Section icon={GitBranch} title="Lineage">
                {j.parent && (
                  <LineageRow
                    lead={j.parent}
                    relation="parent"
                    onClick={() => onSelectLead(j.parent!.id)}
                  />
                )}
                {j.children.map((c) => (
                  <LineageRow key={c.id} lead={c} relation="child" onClick={() => onSelectLead(c.id)} />
                ))}
              </Section>
            )}

            {/* Cost */}
            {j.cost.calls > 0 && (
              <Section icon={DollarSign} title="AI cost">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-bold text-slate-900 dark:text-white">${j.cost.total_usd.toFixed(4)}</span>
                  <span className="text-xs text-slate-400">{j.cost.calls} call{j.cost.calls === 1 ? '' : 's'}</span>
                </div>
                <div className="mt-2 space-y-1">
                  {Object.entries(j.cost.by_kind).map(([kind, usd]) => (
                    <div key={kind} className="flex items-center justify-between text-xs">
                      <span className="capitalize text-slate-500">{kind}</span>
                      <span className="tabular-nums text-slate-600 dark:text-slate-300">${usd.toFixed(4)}</span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {/* Timeline */}
            <Section icon={Clock} title={`Timeline (${j.timeline.length})`}>
              {j.timeline.length === 0 ? (
                <p className="text-xs text-slate-400">No archived events for this lead yet.</p>
              ) : (
                <ol className="relative ml-1 space-y-3 border-l border-slate-200 pl-4 dark:border-slate-700">
                  {j.timeline.map((e, i) => (
                    <li key={i} className="relative">
                      <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-white bg-brand-400 dark:border-slate-900" />
                      <p className="text-[13px] font-medium text-slate-800 dark:text-slate-100">
                        {e.node_label ? humanizeNode(e.node_label) : humanizeEvent(e.event_type)}
                      </p>
                      <p className="text-[11px] text-slate-400">
                        <span className="font-mono">{e.event_type}</span> · {timeAgo(e.occurred_at)}
                      </p>
                    </li>
                  ))}
                </ol>
              )}
            </Section>

            {linkedin && (
              <a
                href={linkedin}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-600 hover:underline"
              >
                <ExternalLink size={14} /> Open LinkedIn profile
              </a>
            )}
          </div>
        )}
      </aside>
    </div>,
    document.body,
  )
}

function Section({ icon: Icon, title, children }: { icon: typeof Clock; title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
        <Icon size={13} /> {title}
      </p>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function LineageRow({ lead, relation, onClick }: { lead: LineageLead; relation: 'parent' | 'child'; onClick: () => void }) {
  const Icon = relation === 'parent' ? ArrowUp : CornerDownRight
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-lg border border-slate-100 px-2.5 py-2 text-left transition-colors hover:border-brand-200 hover:bg-brand-50/50 dark:border-slate-800 dark:hover:border-brand-800 dark:hover:bg-brand-900/10"
    >
      <Icon size={13} className={clsx('shrink-0', relation === 'parent' ? 'text-violet-500' : 'text-slate-400')} />
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-slate-700 dark:text-slate-200">{lead.identity}</span>
      <Badge label={lead.status} asStatus size="xs" />
    </button>
  )
}

// Turn a node_type ("condition.verify_person") into a readable step label —
// the shared curated human name.
function humanizeNode(nodeType: string): string {
  return nodeLabel(nodeType)
}

// Fallback for events with no resolvable node (e.g. lead.converted).
function humanizeEvent(eventType: string): string {
  return eventType.replace(/[._]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
