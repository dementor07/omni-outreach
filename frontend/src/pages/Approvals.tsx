import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserCheck, Check, X, Clock, Sparkles, Save, Wand2, RefreshCw, ExternalLink, Linkedin } from 'lucide-react'
import { approvals, ai, type Approval, type ApprovalEvidence, type AiJob } from '../api/v2'
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
    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-700 dark:bg-slate-800/30">
      <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
        Evidence available to this draft
      </div>
      <div className="space-y-2">
        {sources.map((source, index) => (
          <div key={`${source.kind}-${index}`} className="flex items-start gap-2">
            <span className="mt-0.5 rounded-full bg-white px-2 py-0.5 text-[10px] font-semibold text-violet-700 shadow-sm dark:bg-slate-900 dark:text-violet-300">
              {source.label}
            </span>
            <div className="min-w-0 flex-1 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300">
              {source.excerpt && <span>{source.excerpt}</span>}
              {source.url && (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="ml-1 inline-flex items-center gap-0.5 font-medium text-violet-600 hover:underline dark:text-violet-300"
                >
                  source <ExternalLink size={10} />
                </a>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// A sensible, EDITABLE starting instruction for the playground — the operator
// tweaks it (or clicks a rewrite chip) and re-rolls. The hard humanization rules
// (no em dashes, no AI cliches, self-refine) live in the compose system prompt,
// so this stays focused on WHO we are, the signal to open on, and the shape.
const DEFAULT_INSTRUCTION =
  'Write the first LinkedIn DM to this lead (they just accepted the connection), from Outbound ' +
  'Marketing Hub. We automate outbound: AI finds a company\'s ideal prospects, writes personalized ' +
  'messages, and runs LinkedIn outreach plus follow-ups, so their team keeps the pipeline full ' +
  'without the manual grind.\n\n' +
  'Open on the strongest real buying signal in the facts, in this priority: (1) a specific role ' +
  'they are hiring for, (2) a recent post about scaling / pipeline / lead-gen / outbound, (3) what ' +
  'their website says they do. Name the exact role, listing, or post — do not generalize to "you are ' +
  'hiring". Then bridge to how we solve exactly that, and end with ONE genuine question that follows ' +
  'from the signal.\n\n' +
  'Begin with "Hi {first_name},". 60 to 110 words.\n\n' +
  'Example (hiring signal) — match this voice, not the content:\n' +
  'Hi Sarah,\n' +
  'Saw you are hiring an SDR at Nimbus. Usually that means outbound just went from side project to real priority.\n' +
  'That is the part we take off your plate. We find the right-fit accounts, write the personalized first ' +
  'messages, and run the LinkedIn follow-ups automatically, so whoever you hire spends their day in live ' +
  'conversations instead of building lists.\n' +
  'Are you bringing them on to own outbound end to end, or mostly to work inbound?'

// Rewrite chips append a directive to the instruction, then the operator re-rolls.
const REWRITE_CHIPS: { label: string; hint: string }[] = [
  { label: 'Name the exact role', hint: 'If they are hiring, name the exact role from the listing; do not generalize.' },
  { label: 'Warmer', hint: 'Warmer and more personal, founder to founder.' },
  { label: 'Shorter', hint: 'Keep it tight — 3 short lines max.' },
  { label: 'More direct', hint: 'Be more direct and confident; get to the point faster.' },
  { label: 'Lead with our outcome', hint: 'Lead with the outcome we drive: a full pipeline without manual outbound.' },
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
  { value: 'claude-sonnet-5', label: 'Sonnet 5 — balanced' },
  { value: 'claude-opus-5', label: 'Opus 5 — best' },
]

interface ComposeSettings {
  instruction: string
  tone: ComposeTone
  channel: ComposeChannel
  maxWords: number
  model: string
}

const DEFAULT_SETTINGS: ComposeSettings = {
  instruction: DEFAULT_INSTRUCTION,
  tone: 'warm',
  channel: 'linkedin',
  maxWords: 120,
  model: 'claude-haiku-4-5-20251001',
}

// Poll the ad-hoc AI job until the compose draft is ready. The engine is async
// (POST /ai/jobs -> ai.compose.completed -> projector), so we poll the job by id.
// Every ai.compose knob is passed through `config`, which the worker reads.
async function regenerateDraft(leadId: string, s: ComposeSettings): Promise<string> {
  const { job_id } = await ai.runJob({
    kind: 'compose',
    entity_type: 'lead',
    entity_id: leadId,
    config: {
      instruction: s.instruction,
      tone: s.tone,
      channel: s.channel,
      max_words: s.maxWords,
      model: s.model,
    },
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
  // null = not editing; otherwise the working draft text.
  const [editing, setEditing] = useState<string | null>(null)
  const [playgroundOpen, setPlaygroundOpen] = useState(false)
  const [settings, setSettings] = useState<ComposeSettings>(DEFAULT_SETTINGS)
  const patch = (p: Partial<ComposeSettings>) => setSettings((s) => ({ ...s, ...p }))

  const invalidate = () => qc.invalidateQueries({ queryKey: ['approvals'] })

  const saveMut = useMutation({
    mutationFn: () => approvals.updateDraft(approval.id, editing ?? ''),
    onSuccess: () => {
      toast.success('Draft updated')
      setEditing(null)
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
    mutationFn: () => regenerateDraft(approval.lead_id, settings),
    onSuccess: (draft) => {
      // Land the regenerated text in the editable draft so it can be reviewed,
      // tweaked, then Saved (which persists it for the send) before Approve.
      setEditing(draft)
      toast.success('Regenerated — review, save, then approve')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not regenerate'),
  })

  const busy = saveMut.isPending || resolveMut.isPending || regenMut.isPending

  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-3">
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
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
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
              {approval.sending_account_id && (
                <span className="ml-1 font-mono text-[10px] text-slate-400" title={approval.sending_account_id}>
                  ({approval.sending_account_id})
                </span>
              )}
            </div>
          </div>
          <p className="mt-2 text-[13px] font-medium text-slate-700 dark:text-slate-200">{approval.prompt || 'Approval requested'}</p>
        </div>
        <Badge label="pending" variant="warning" dot />
      </div>

      <EvidenceSources sources={approval.evidence_sources} />

      {/* AI draft-review (B1): present when an upstream ai.compose populated it. */}
      {(approval.draft !== null || editing !== null) && (
        <div className="mt-3 rounded-lg border border-violet-200 bg-violet-50/50 p-3 dark:border-violet-900/40 dark:bg-violet-900/10">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold text-violet-700 dark:text-violet-300">
            <Sparkles size={12} />
            AI draft — review before approving
          </div>
          {editing !== null ? (
            <textarea
              value={editing}
              onChange={(e) => setEditing(e.target.value)}
              rows={5}
              aria-label="AI draft"
              placeholder="Edit the AI-composed draft…"
              className="w-full resize-none rounded-md border border-slate-200 bg-white px-2.5 py-2 text-[13px] text-slate-900 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40"
            />
          ) : (
            <p className="whitespace-pre-wrap text-[13px] leading-relaxed text-slate-700 dark:text-slate-200">{approval.draft}</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {editing !== null ? (
              <>
                <Button variant="primary" size="sm" icon={Save} onClick={() => saveMut.mutate()} disabled={busy}>Save draft</Button>
                <Button variant="ghost" size="sm" onClick={() => setEditing(null)} disabled={busy}>Cancel</Button>
              </>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => setEditing(approval.draft ?? '')} disabled={busy}>Edit draft</Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              icon={Wand2}
              onClick={() => setPlaygroundOpen((o) => !o)}
              disabled={busy}
            >
              {playgroundOpen ? 'Hide playground' : 'Regenerate…'}
            </Button>
          </div>

          {/* Playground: every ai.compose knob — instruction, tone, length,
              model, channel — then re-roll the draft from this lead's data. */}
          {playgroundOpen && (
            <div className="mt-3 space-y-2.5 rounded-md border border-slate-200 bg-white/70 p-2.5 dark:border-slate-700 dark:bg-slate-900/40">
              <div className="flex items-center justify-between">
                <div className="text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                  Compose playground — same options as the ai.compose node
                </div>
                <button
                  type="button"
                  disabled={regenMut.isPending}
                  onClick={() => setSettings(DEFAULT_SETTINGS)}
                  className="rounded-full px-2 py-0.5 text-[11px] text-slate-400 hover:text-slate-600 disabled:opacity-50 dark:hover:text-slate-200"
                >
                  Reset all
                </button>
              </div>

              {/* Row of the four scalar knobs. */}
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

              {/* Instruction — the prompt itself. */}
              <div>
                <div className="mb-1 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                  Instruction — edit freely
                </div>
                <textarea
                  value={settings.instruction}
                  onChange={(e) => patch({ instruction: e.target.value })}
                  rows={7}
                  aria-label="Regeneration instruction"
                  disabled={regenMut.isPending}
                  className="w-full resize-y rounded-md border border-slate-200 bg-white px-2.5 py-2 font-mono text-[12px] leading-relaxed text-slate-800 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40"
                />
              </div>

              {/* Rewrite chips append a directive to the instruction. */}
              <div className="flex flex-wrap items-center gap-1.5">
                {REWRITE_CHIPS.map((c) => (
                  <button
                    key={c.label}
                    type="button"
                    disabled={regenMut.isPending}
                    onClick={() => patch({ instruction: `${settings.instruction.trim()}\n${c.hint}`.trim() })}
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 transition hover:border-violet-300 hover:text-violet-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-violet-700"
                  >
                    + {c.label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={RefreshCw}
                  onClick={() => regenMut.mutate()}
                  disabled={regenMut.isPending || !settings.instruction.trim()}
                >
                  {regenMut.isPending ? 'Generating…' : 'Generate new draft'}
                </Button>
                <span className="text-[11px] text-slate-400">Personalized from this lead's data. Doesn't send — lands in the draft above.</span>
              </div>
            </div>
          )}
        </div>
      )}

      <div className="mt-3 flex items-center gap-2">
        <Button variant="primary" size="sm" icon={Check} onClick={() => resolveMut.mutate('approved')} disabled={busy || editing !== null}>Approve</Button>
        <Button variant="secondary" size="sm" icon={X} onClick={() => resolveMut.mutate('rejected')} disabled={busy || editing !== null}>Reject</Button>
      </div>
    </Card>
  )
}
