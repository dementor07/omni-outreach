import { useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserCheck, Check, X, Clock, Sparkles, Save, Wand2, RefreshCw, ExternalLink, Linkedin, TextSelect, Trash2 } from 'lucide-react'
import { approvals, ai, type Approval, type ApprovalEvidence, type AiJob, type RewriteDirective } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'
import { timeAgo } from '../lib/format'

export default function Approvals() {
  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Approvals"
        eyebrow="Human-in-the-loop"
        title="Approvals"
        description="Drafts and decisions parked by human-approval nodes. Review the AI draft, regenerate it with a different angle, then approve to advance or reject to branch."
      />
      <ApprovalQueue />
    </div>
  )
}

export function ApprovalQueue({ campaignId }: { campaignId?: string }) {
  const { data: pending = [], isLoading } = useQuery({
    queryKey: ['approvals', campaignId ?? 'all'],
    queryFn: () => approvals.list(campaignId),
  })
  const [campaign, setCampaign] = useState<string>('all')

  // Distinct campaigns present in the queue, with counts — so a campaign-specific
  // pile-up (e.g. duplicate approvals in one campaign) is obvious at a glance.
  const campaigns = useMemo(() => {
    const counts = new Map<string, { id: string; name: string; n: number }>()
    for (const a of pending) {
      const id = a.campaign_id ?? 'none'
      const cur = counts.get(id) ?? { id, name: a.campaign_name ?? 'No campaign', n: 0 }
      cur.n += 1
      counts.set(id, cur)
    }
    return [...counts.values()].sort((x, y) => y.n - x.n)
  }, [pending])

  const shown = campaign === 'all' ? pending : pending.filter((a) => (a.campaign_id ?? 'none') === campaign)

  return (
    <div className="space-y-3">
      {/* Campaign filter: scope the queue to one campaign to isolate campaign-specific issues. */}
      {!campaignId && campaigns.length > 1 && (
        <div className="flex flex-wrap items-center gap-2">
          <FilterChip label="All campaigns" count={pending.length} active={campaign === 'all'} onClick={() => setCampaign('all')} />
          {campaigns.map((c) => (
            <FilterChip key={c.id} label={c.name} count={c.n} active={campaign === c.id} onClick={() => setCampaign(c.id)} />
          ))}
        </div>
      )}

      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : shown.length === 0 ? (
        <Card><EmptyState icon={UserCheck} title="No pending approvals" description="When a human-approval node parks a lead, it shows up here." /></Card>
      ) : (
        <div className="space-y-3">
          {shown.map((a) => <ApprovalCard key={a.id} approval={a} />)}
        </div>
      )}
    </div>
  )
}

function FilterChip({ label, count, active, onClick }: { label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12px] font-medium transition ' +
        (active
          ? 'border-violet-400 bg-violet-50 text-violet-700 dark:border-violet-600 dark:bg-violet-900/30 dark:text-violet-200'
          : 'border-slate-200 bg-white text-slate-600 hover:border-violet-300 hover:text-violet-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-violet-700')
      }
    >
      {label}
      <span className={'rounded-full px-1.5 text-[11px] ' + (active ? 'bg-violet-200/70 text-violet-800 dark:bg-violet-800/60 dark:text-violet-100' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400')}>{count}</span>
    </button>
  )
}

function EvidenceSources({ sources }: { sources: ApprovalEvidence[] }) {
  if (sources.length === 0) {
    return (
      <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-[11px] text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-300">
        No profile, post, hiring, or website evidence was attached to this draft. Verify it manually before approving.
      </div>
    )
  }
  return (
    <div className="inset-surface mt-3 p-3.5">
      <div className="mb-2.5 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">
        Evidence available to this draft
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {sources.map((source, index) => (
          <div key={`${source.kind}-${index}`} className="rounded-lg border border-slate-200/80 bg-white/90 p-2.5 dark:border-slate-700 dark:bg-slate-900/70">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-violet-700 dark:text-violet-300">
                {source.label}
              </span>
              {source.url && (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex shrink-0 items-center gap-0.5 text-[10px] font-semibold text-violet-600 hover:underline dark:text-violet-300"
                >
                  Open <ExternalLink size={10} />
                </a>
              )}
            </div>
            {source.excerpt && <p className="mt-1.5 line-clamp-3 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">{source.excerpt}</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

// Whole-draft notes stay separate from the campaign's source instruction. This
// preserves provenance and makes the operator's one-off change obvious.
const REWRITE_CHIPS: { label: string; hint: string }[] = [
  { label: 'Warmer', hint: 'Warmer and more personal, founder to founder.' },
  { label: 'Shorter', hint: 'Keep it tight — 3 short lines max.' },
  { label: 'More direct', hint: 'Be more direct and confident; get to the point faster.' },
  { label: 'Use stronger evidence', hint: 'Lead with the strongest concrete fact available in the profile, post, hiring, or website evidence.' },
]

// The knobs the ai.compose node exposes, surfaced 1:1 in the playground.
type ComposeTone = 'warm' | 'professional' | 'casual' | 'direct'
type ComposeChannel = 'linkedin' | 'email' | 'sms' | 'whatsapp'
const TONES: { value: ComposeTone; label: string }[] = [
  { value: 'warm', label: 'Warm' },
  { value: 'professional', label: 'Professional' },
  { value: 'casual', label: 'Casual' },
  { value: 'direct', label: 'Direct' },
]
const CHANNELS: { value: ComposeChannel; label: string }[] = [
  { value: 'linkedin', label: 'LinkedIn' },
  { value: 'email', label: 'Email' },
  { value: 'sms', label: 'SMS' },
  { value: 'whatsapp', label: 'WhatsApp' },
]
const LENGTHS: { value: number; label: string }[] = [
  { value: 60, label: 'Very short (~60w)' },
  { value: 90, label: 'Short (~90w)' },
  { value: 120, label: 'Medium (~120w)' },
  { value: 160, label: 'Long (~160w)' },
]
// Values must match backend COMPOSE_MODELS; anything else falls back to Haiku.
const MODELS: { value: string; label: string }[] = [
  { value: 'claude-haiku-4-5-20251001', label: 'Haiku — fast & cheap' },
  { value: 'claude-sonnet-4-6', label: 'Sonnet 4.6 — campaign default' },
  { value: 'claude-sonnet-5', label: 'Sonnet 5 — balanced' },
  { value: 'claude-opus-5', label: 'Opus 5 — best' },
]

interface ComposeSettings {
  instruction: string
  tone: ComposeTone
  channel: ComposeChannel
  maxWords: number
  model: string
  rewriteNote: string
}

function settingsFromApproval(approval: Approval): ComposeSettings {
  const source = approval.compose_context
  return {
    instruction: source?.instruction ?? '',
    tone: (source?.tone as ComposeTone) || 'professional',
    channel: (source?.channel as ComposeChannel) || 'email',
    maxWords: source?.max_words ?? 120,
    model: source?.model || 'claude-haiku-4-5-20251001',
    rewriteNote: '',
  }
}

// Poll the ad-hoc AI job until the compose draft is ready. The engine is async
// (POST /ai/jobs -> ai.compose.completed -> projector), so we poll the job by id.
// Every ai.compose knob is passed through `config`, which the worker reads.
async function regenerateDraft(
  approvalId: string,
  originalDraft: string,
  s: ComposeSettings,
  directives: RewriteDirective[],
): Promise<string> {
  const { job_id } = await approvals.regenerate(approvalId, {
    original_draft: originalDraft,
    campaign_instruction: s.instruction,
    rewrite_note: s.rewriteNote,
    directives,
    tone: s.tone,
    channel: s.channel,
    max_words: s.maxWords,
    model: s.model,
  })
  for (let attempt = 0; attempt < 30; attempt++) {
    await new Promise((r) => setTimeout(r, 2000))
    const jobs = await ai.jobs({ kind: 'compose', limit: 25 })
    const job: AiJob | undefined = jobs.find((j) => j.id === job_id)
    if (job?.status === 'done') {
      const draft = (job.output as { draft?: string })?.draft
      if (draft && draft.trim()) return draft
      throw new Error('The model returned an empty draft — try again.')
    }
    if (job?.status === 'failed') throw new Error(job.error || 'Regeneration failed.')
  }
  throw new Error('Timed out waiting for the new draft.')
}

// A compact labeled <select> matching the playground's density.
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
      {label}
      {children}
    </label>
  )
}
const selectCls =
  'rounded-md border border-slate-200 bg-white px-2 py-1.5 text-[12px] font-normal text-slate-800 ' +
  'focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 disabled:opacity-60 ' +
  'dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40'

function ApprovalCard({ approval }: { approval: Approval }) {
  const qc = useQueryClient()
  const toast = useToast()
  const draftRef = useRef<HTMLTextAreaElement>(null)
  // null = not editing; otherwise the working draft text.
  const [editing, setEditing] = useState<string | null>(null)
  const [playgroundOpen, setPlaygroundOpen] = useState(false)
  const sourceSettings = useMemo(() => settingsFromApproval(approval), [approval])
  const [settings, setSettings] = useState<ComposeSettings>(() => settingsFromApproval(approval))
  const [directives, setDirectives] = useState<RewriteDirective[]>([])
  const [selection, setSelection] = useState<{ start: number; end: number; text: string } | null>(null)
  const [selectionInstruction, setSelectionInstruction] = useState('')
  const patch = (p: Partial<ComposeSettings>) => setSettings((s) => ({ ...s, ...p }))

  const updateSelection = () => {
    const textarea = draftRef.current
    if (!textarea || textarea.selectionEnd <= textarea.selectionStart) {
      setSelection(null)
      return
    }
    setSelection({
      start: textarea.selectionStart,
      end: textarea.selectionEnd,
      text: textarea.value.slice(textarea.selectionStart, textarea.selectionEnd),
    })
  }

  const addDirective = () => {
    if (!selection) {
      toast.error('Select the exact words you want to change first.')
      return
    }
    if (selectionInstruction.trim().length < 2) {
      toast.error('Add a short rewrite note for the selected text.')
      return
    }
    setDirectives((current) => [
      ...current,
      {
        start: selection.start,
        end: selection.end,
        selected_text: selection.text,
        instruction: selectionInstruction.trim(),
      },
    ])
    setSelectionInstruction('')
    setSelection(null)
  }

  const togglePlayground = () => {
    const opening = !playgroundOpen
    setPlaygroundOpen(opening)
    if (opening) {
      setEditing((current) => current ?? approval.draft ?? '')
      setSettings(sourceSettings)
      setDirectives([])
      setSelection(null)
    }
  }

  const invalidate = () => qc.invalidateQueries({ queryKey: ['approvals'] })

  const saveMut = useMutation({
    mutationFn: () => approvals.updateDraft(approval.id, editing ?? ''),
    onSuccess: () => {
      toast.success('Draft updated')
      setEditing(null)
      setPlaygroundOpen(false)
      setDirectives([])
      setSelection(null)
      setTimeout(invalidate, 400)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not save draft'),
  })

  const resolveMut = useMutation({
    mutationFn: (handle: 'approved' | 'rejected') => approvals.resolve(approval.id, handle),
    onSuccess: (_res, handle) => {
      toast.success(handle === 'approved' ? 'Approved — lead advancing' : 'Rejected — lead branching')
      setTimeout(invalidate, 400)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not resolve'),
  })

  const regenMut = useMutation({
    mutationFn: () => regenerateDraft(approval.id, editing ?? approval.draft ?? '', settings, directives),
    onSuccess: (draft) => {
      // Land the regenerated text in the editable draft so it can be reviewed,
      // tweaked, then Saved (which persists it for the send) before Approve.
      setEditing(draft)
      setDirectives([])
      setSelection(null)
      toast.success('Regenerated — review, save, then approve')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not regenerate'),
  })

  const busy = saveMut.isPending || resolveMut.isPending || regenMut.isPending

  return (
    <Card padding="md" className="relative overflow-hidden border-l-4 border-l-amber-300 dark:border-l-amber-500/70">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <Clock size={11} />
            <span>{timeAgo(approval.created_at)}</span>
            {approval.campaign_name && (
              <>
                <span className="text-slate-300">·</span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">{approval.campaign_name}</span>
              </>
            )}
          </div>
          <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px]">
            <div className="flex min-w-0 items-center gap-1.5">
              <Linkedin size={13} className="shrink-0 text-sky-600" />
              {approval.prospect_linkedin_url ? (
                <a
                  href={approval.prospect_linkedin_url}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate font-semibold text-slate-800 hover:text-violet-700 hover:underline dark:text-slate-100 dark:hover:text-violet-300"
                >
                  {approval.prospect_name || `Lead ${approval.lead_id.slice(0, 8)}`}
                </a>
              ) : (
                <span className="font-semibold text-slate-800 dark:text-slate-100">
                  {approval.prospect_name || `Lead ${approval.lead_id.slice(0, 8)}`}
                </span>
              )}
              {approval.prospect_company && <span className="text-slate-400">at {approval.prospect_company}</span>}
            </div>
            <div className="text-slate-500 dark:text-slate-400">
              Connecting from <span className="font-semibold text-slate-700 dark:text-slate-200">{approval.sending_account_name || 'unknown seat'}</span>
              {approval.sending_account_id && <span className="ml-1 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 dark:bg-slate-800" title={approval.sending_account_id}>ID {approval.sending_account_id.slice(0, 8)}</span>}
            </div>
          </div>
          <p className="mt-2 text-[13px] font-medium text-slate-700 dark:text-slate-200">{approval.prompt || 'Approval requested'}</p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2 lg:flex-col lg:items-end">
          <Badge label="pending review" variant="warning" dot />
          <div className="flex items-center gap-2">
            <Button variant="primary" size="sm" icon={Check} onClick={() => resolveMut.mutate('approved')} disabled={busy || editing !== null}>Approve</Button>
            <Button variant="secondary" size="sm" icon={X} onClick={() => resolveMut.mutate('rejected')} disabled={busy || editing !== null}>Reject</Button>
          </div>
          <span className="hidden text-[10px] text-slate-400 lg:block">Review evidence and draft first</span>
        </div>
      </div>

      <EvidenceSources sources={approval.evidence_sources} />

      {/* AI draft-review (B1): present when an upstream ai.compose populated it. */}
      {(approval.draft !== null || editing !== null) && (
        <div className="mt-3 rounded-xl border border-violet-200/80 bg-violet-50/45 p-3.5 dark:border-violet-900/40 dark:bg-violet-900/10">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-violet-700 dark:text-violet-300">
            <Sparkles size={12} />
            AI draft — review before approving
          </div>
          {editing !== null ? (
            <textarea
              ref={draftRef}
              value={editing}
              onChange={(e) => {
                setEditing(e.target.value)
                if (directives.length > 0) setDirectives([])
                setSelection(null)
              }}
              onSelect={playgroundOpen ? updateSelection : undefined}
              rows={5}
              aria-label="AI draft"
              placeholder="Edit the AI-composed draft…"
              className="w-full resize-none rounded-md border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-900 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40"
            />
          ) : (
            <p className="max-w-[82ch] whitespace-pre-wrap text-[13px] leading-6 text-slate-700 dark:text-slate-200">{approval.draft}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {editing !== null ? (
              <>
                <Button variant="primary" size="sm" icon={Save} onClick={() => saveMut.mutate()} disabled={busy}>Save draft</Button>
                <Button variant="ghost" size="sm" onClick={() => {
                  setEditing(null)
                  setPlaygroundOpen(false)
                  setDirectives([])
                  setSelection(null)
                }} disabled={busy}>Cancel</Button>
              </>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => setEditing(approval.draft ?? '')} disabled={busy}>Edit draft</Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              icon={Wand2}
              onClick={togglePlayground}
              disabled={busy || !approval.compose_context}
              title={approval.compose_context ? 'Rewrite with campaign context' : 'No unambiguous upstream ai.compose node was found'}
            >
              {playgroundOpen ? 'Hide rewrite studio' : 'Regenerate with context…'}
            </Button>
          </div>
          {!approval.compose_context && (
            <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">
              Contextual regeneration is unavailable because this approval does not resolve to exactly one upstream AI compose node. The draft can still be edited manually.
            </p>
          )}

          {/* Approval-specific rewrite studio. Provenance comes from the direct
              upstream ai.compose node; selected ranges stay anchored to this
              exact working draft and are validated again by the backend. */}
          {playgroundOpen && (
            <div className="mt-4 space-y-4 rounded-xl border border-violet-200 bg-white p-4 shadow-sm dark:border-violet-900/60 dark:bg-slate-950/70">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <div className="flex flex-wrap items-center gap-2 text-[11px] font-bold uppercase tracking-[0.12em] text-violet-700 dark:text-violet-300">
                    <Wand2 size={13} /> Contextual rewrite studio
                    <span className="rounded-full bg-violet-50 px-2 py-0.5 font-mono text-[9px] tracking-normal text-violet-600 dark:bg-violet-950/50 dark:text-violet-300">
                      node {approval.compose_context?.node_id.slice(0, 8)}
                    </span>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                    Inherits this campaign message's real instruction and the evidence shown above. Regeneration only creates a review draft.
                  </p>
                </div>
                <button
                  type="button"
                  disabled={regenMut.isPending}
                  onClick={() => {
                    setSettings(sourceSettings)
                    setDirectives([])
                    setSelection(null)
                  }}
                  className="rounded-full px-2 py-0.5 text-[11px] text-slate-400 hover:text-slate-600 disabled:opacity-50 dark:hover:text-slate-200"
                >
                  Reset to campaign
                </button>
              </div>

              <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
                <section className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-900/50">
                  <div className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-700 dark:text-slate-200">
                    <TextSelect size={13} className="text-violet-500" /> Annotate exact wording
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
                    Select words in the draft above, describe only how that selection should change, then add the note.
                  </p>
                  {selection ? (
                    <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50/80 p-2.5 dark:border-violet-900/50 dark:bg-violet-950/25">
                      <div className="text-[10px] font-bold uppercase tracking-[0.12em] text-violet-600">Current selection</div>
                      <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-[12px] font-medium text-slate-800 dark:text-slate-100">“{selection.text}”</p>
                    </div>
                  ) : (
                    <div className="mt-3 rounded-lg border border-dashed border-slate-300 px-3 py-4 text-center text-[11px] text-slate-400 dark:border-slate-700">
                      No text selected yet
                    </div>
                  )}
                  <div className="mt-2 flex flex-col gap-2 sm:flex-row xl:flex-col 2xl:flex-row">
                    <input
                      value={selectionInstruction}
                      onChange={(e) => setSelectionInstruction(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && selection) {
                          e.preventDefault()
                          addDirective()
                        }
                      }}
                      placeholder="e.g. Use the exact hiring role from the evidence"
                      disabled={regenMut.isPending}
                      className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                    />
                    <Button variant="secondary" size="sm" icon={TextSelect} onClick={addDirective} disabled={!selection || regenMut.isPending}>
                      Add note
                    </Button>
                  </div>
                  {directives.length > 0 && (
                    <div className="mt-3 space-y-2">
                      {directives.map((directive, index) => (
                        <div key={`${directive.start}-${directive.end}-${index}`} className="rounded-lg border border-slate-200 bg-white p-2.5 dark:border-slate-700 dark:bg-slate-950">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-[11px] font-semibold text-slate-700 dark:text-slate-200">“{directive.selected_text}”</p>
                              <p className="mt-0.5 text-[11px] text-slate-500">{directive.instruction}</p>
                            </div>
                            <button type="button" aria-label="Remove rewrite note" onClick={() => setDirectives((current) => current.filter((_, i) => i !== index))} className="shrink-0 rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/30">
                              <Trash2 size={12} />
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </section>

                <section className="space-y-3">
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                    <Field label="Tone">
                      <select className={selectCls} value={settings.tone} disabled={regenMut.isPending}
                        onChange={(e) => patch({ tone: e.target.value as ComposeTone })}>
                        {TONES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </select>
                    </Field>
                    <Field label="Length">
                      <select className={selectCls} value={settings.maxWords} disabled={regenMut.isPending}
                        onChange={(e) => patch({ maxWords: Number(e.target.value) })}>
                        {LENGTHS.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
                      </select>
                    </Field>
                    <Field label="Model">
                      <select className={selectCls} value={settings.model} disabled={regenMut.isPending}
                        onChange={(e) => patch({ model: e.target.value })}>
                        {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                      </select>
                    </Field>
                    <Field label="Channel">
                      <select className={selectCls} value={settings.channel} disabled={regenMut.isPending}
                        onChange={(e) => patch({ channel: e.target.value as ComposeChannel })}>
                        {CHANNELS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                      </select>
                    </Field>
                  </div>

                  <div>
                    <div className="mb-1 flex items-center justify-between gap-2 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                      <span>Campaign instruction</span>
                      <span className="font-normal text-slate-400">Inherited from this message node</span>
                    </div>
                    <textarea
                      value={settings.instruction}
                      onChange={(e) => patch({ instruction: e.target.value })}
                      rows={5}
                      aria-label="Campaign compose instruction"
                      disabled={regenMut.isPending}
                      className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-800 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40"
                    />
                  </div>

                  <div>
                    <div className="mb-1 text-[11px] font-semibold text-slate-600 dark:text-slate-300">Whole-draft note <span className="font-normal text-slate-400">(optional)</span></div>
                    <textarea
                      value={settings.rewriteNote}
                      onChange={(e) => patch({ rewriteNote: e.target.value })}
                      rows={2}
                      placeholder="What should change across the message while keeping its campaign intent?"
                      disabled={regenMut.isPending}
                      className="w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-[12px] leading-relaxed text-slate-800 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5">
                    {REWRITE_CHIPS.map((c) => (
                      <button
                        key={c.label}
                        type="button"
                        disabled={regenMut.isPending}
                        onClick={() => patch({ rewriteNote: `${settings.rewriteNote.trim()}\n${c.hint}`.trim() })}
                        className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 transition hover:border-violet-300 hover:text-violet-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-violet-700"
                      >
                        + {c.label}
                      </button>
                    ))}
                  </div>
                </section>
              </div>

              <div className="flex flex-col gap-2 border-t border-slate-100 pt-3 sm:flex-row sm:items-center">
                <Button
                  variant="primary"
                  size="sm"
                  icon={RefreshCw}
                  onClick={() => regenMut.mutate()}
                  disabled={regenMut.isPending || !settings.instruction.trim() || !(editing ?? '').trim()}
                >
                  {regenMut.isPending ? 'Generating…' : directives.length > 0 ? `Rewrite with ${directives.length} annotation${directives.length === 1 ? '' : 's'}` : 'Regenerate draft'}
                </Button>
                <span className="text-[11px] text-slate-400">Uses campaign intent + current draft + lead evidence. Nothing is approved or sent.</span>
              </div>
            </div>
          )}
        </div>
      )}

    </Card>
  )
}
