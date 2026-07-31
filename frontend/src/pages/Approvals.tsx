import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { UserCheck, Check, X, Clock, Sparkles, Save, Wand2, RefreshCw } from 'lucide-react'
import { approvals, ai, type Approval, type AiJob } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'
import { timeAgo } from '../lib/format'

export default function Approvals() {
  const { data: pending = [], isLoading } = useQuery({
    queryKey: ['approvals'],
    queryFn: approvals.list,
  })

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Approvals"
        eyebrow="Human-in-the-loop"
        title="Approvals"
        description="Drafts and decisions parked by human-approval nodes. Review the AI draft, regenerate it with a different angle, then approve to advance or reject to branch."
      />

      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : pending.length === 0 ? (
        <Card><EmptyState icon={UserCheck} title="No pending approvals" description="When a human-approval node parks a lead, it shows up here." /></Card>
      ) : (
        <div className="space-y-3">
          {pending.map((a) => <ApprovalCard key={a.id} approval={a} />)}
        </div>
      )}
    </div>
  )
}

// A sensible, EDITABLE starting instruction for the playground — the operator
// tweaks it (or clicks a tone chip) and re-rolls. Kept product-aware so a
// regenerated draft still pitches what we do.
const DEFAULT_INSTRUCTION =
  'Write a warm, human LinkedIn message. Open with ONE specific, personalized observation ' +
  'about them or their company. Naturally weave in how Outbound Marketing Hub (AI prospect ' +
  'discovery, hyper-personalized outreach, automated follow-ups) could help a team like theirs. ' +
  'End with ONE engaging question. Concise, conversational, no emojis, no sign-off.'

const TONE_CHIPS: { label: string; hint: string }[] = [
  { label: 'Warmer', hint: 'Make the tone noticeably warmer and more personal.' },
  { label: 'Shorter', hint: 'Keep it very short — 2 to 3 lines max.' },
  { label: 'More direct', hint: 'Be more direct and confident; get to the point faster.' },
  { label: 'More about us', hint: 'Lean more into what Outbound Marketing Hub does and the outcome it drives.' },
  { label: 'Casual', hint: 'Use a casual, founder-to-founder tone.' },
]

// Poll the ad-hoc AI job until the compose draft is ready. The engine is async
// (POST /ai/jobs -> ai.compose.completed -> projector), so we poll the job by id.
async function regenerateDraft(leadId: string, instruction: string): Promise<string> {
  const { job_id } = await ai.runJob({
    kind: 'compose',
    entity_type: 'lead',
    entity_id: leadId,
    config: { instruction },
  })
  for (let attempt = 0; attempt < 24; attempt++) {
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

function ApprovalCard({ approval }: { approval: Approval }) {
  const qc = useQueryClient()
  const toast = useToast()
  // null = not editing; otherwise the working draft text.
  const [editing, setEditing] = useState<string | null>(null)
  const [playgroundOpen, setPlaygroundOpen] = useState(false)
  const [instruction, setInstruction] = useState(DEFAULT_INSTRUCTION)

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
    mutationFn: () => regenerateDraft(approval.lead_id, instruction),
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
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <Clock size={11} />
            <span>{timeAgo(approval.created_at)}</span>
            <span className="text-slate-300">·</span>
            <span>lead {approval.lead_id.slice(0, 8)}</span>
          </div>
          <p className="mt-2 text-[13px] font-medium text-slate-700 dark:text-slate-200">{approval.prompt || 'Approval requested'}</p>
        </div>
        <Badge label="pending" variant="warning" dot />
      </div>

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

          {/* Playground: tweak the instruction / tone and re-roll the draft. */}
          {playgroundOpen && (
            <div className="mt-3 rounded-md border border-slate-200 bg-white/70 p-2.5 dark:border-slate-700 dark:bg-slate-900/40">
              <div className="mb-1.5 text-[11px] font-semibold text-slate-600 dark:text-slate-300">
                Instruction — edit freely, then regenerate
              </div>
              <textarea
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                rows={3}
                aria-label="Regeneration instruction"
                disabled={regenMut.isPending}
                className="w-full resize-none rounded-md border border-slate-200 bg-white px-2.5 py-2 text-[12px] text-slate-800 focus:border-violet-400 focus:outline-none focus:ring-2 focus:ring-violet-100 disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:focus:ring-violet-900/40"
              />
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {TONE_CHIPS.map((c) => (
                  <button
                    key={c.label}
                    type="button"
                    disabled={regenMut.isPending}
                    onClick={() => setInstruction((prev) => `${prev.trim()} ${c.hint}`.trim())}
                    className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-medium text-slate-600 transition hover:border-violet-300 hover:text-violet-700 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300 dark:hover:border-violet-700"
                  >
                    {c.label}
                  </button>
                ))}
                <button
                  type="button"
                  disabled={regenMut.isPending}
                  onClick={() => setInstruction(DEFAULT_INSTRUCTION)}
                  className="rounded-full px-2 py-1 text-[11px] text-slate-400 hover:text-slate-600 disabled:opacity-50 dark:hover:text-slate-200"
                >
                  Reset
                </button>
              </div>
              <div className="mt-2">
                <Button
                  variant="primary"
                  size="sm"
                  icon={RefreshCw}
                  onClick={() => regenMut.mutate()}
                  disabled={regenMut.isPending || !instruction.trim()}
                >
                  {regenMut.isPending ? 'Generating…' : 'Generate new draft'}
                </Button>
                <span className="ml-2 text-[11px] text-slate-400">Personalized from this lead's data. Doesn't send — lands in the draft above.</span>
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
