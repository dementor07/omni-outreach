/**
 * AGENT-THREAD-001 — the persistent chat box for a view or a campaign.
 *
 * One panel serves both surfaces because a session is defined by its target,
 * not by the page it is rendered on. The only thing the host supplies is what
 * an anchor *means* there: a widget on Overview, a node on the canvas.
 *
 * The distinction the design rests on is the first thing in the composer, not
 * buried in a menu. Ask is free and always safe — it can never produce a change.
 * Instruct queues work that comes back as a reviewed proposal a human applies.
 * Making that choice explicit is the point: it is the difference between
 * reading a dashboard and editing a campaign that is messaging real people.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Bot,
  CircleHelp,
  Clock,
  Loader2,
  MapPin,
  PencilLine,
  Send,
  ShieldAlert,
  User,
  X,
} from 'lucide-react'
import {
  agentThreads,
  type AgentThread,
  type AgentThreadTurn,
  type ThreadAnchor,
  type ThreadTargetType,
} from '../api/v2'
import Button from './Button'
import { useToast } from './Toast'

interface Props {
  targetType: ThreadTargetType
  targetId: string
  /** ref -> human label, so a pin reads as a name rather than a UUID. */
  anchorLabels: Record<string, string>
  /** Anchors the host surface has staged (a selected node or widget). */
  pendingAnchors: ThreadAnchor[]
  onStageAnchor: (anchor: ThreadAnchor) => void
  onRemoveAnchor: (ref: string) => void
  onClearAnchors: () => void
  /** What the host currently has selected, offered as the next thing to pin. */
  selectedRef?: string | null
  onClose: () => void
  /** Called when a turn lands, so the host can drop its selection UI. */
  onSent?: () => void
}

type Intent = 'question' | 'instruction'

const POLL_MS = 4000

function label(labels: Record<string, string>, ref: string): string {
  return labels[ref] ?? ref.slice(0, 8)
}

function when(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function AnchorPill({
  anchor,
  labels,
  onRemove,
}: {
  anchor: ThreadAnchor
  labels: Record<string, string>
  onRemove?: () => void
}) {
  return (
    <span className="inline-flex max-w-full items-start gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs dark:border-slate-700 dark:bg-slate-800/70">
      <MapPin size={12} className="mt-0.5 shrink-0 text-brand-500" />
      <span className="min-w-0">
        <span className="font-medium text-slate-700 dark:text-slate-200">
          {label(labels, anchor.ref)}
        </span>
        <span className="text-slate-500 dark:text-slate-400"> — {anchor.note}</span>
      </span>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-0.5 shrink-0 rounded text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          aria-label={`Remove annotation on ${label(labels, anchor.ref)}`}
        >
          <X size={12} />
        </button>
      )}
    </span>
  )
}

function TurnBubble({
  turn,
  labels,
}: {
  turn: AgentThreadTurn
  labels: Record<string, string>
}) {
  const mine = turn.role === 'human'
  const Icon = mine ? (turn.intent === 'question' ? CircleHelp : PencilLine) : Bot
  return (
    <div className={`flex gap-2.5 ${mine ? '' : 'flex-row'}`}>
      <div
        className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${
          mine
            ? 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
            : 'bg-brand-50 text-brand-600 dark:bg-brand-950/50 dark:text-brand-300'
        }`}
      >
        <Icon size={13} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-xs font-medium text-slate-700 dark:text-slate-200">
            {mine ? (turn.intent === 'question' ? 'You asked' : 'You instructed') : 'Agent'}
          </span>
          <span className="text-[11px] text-slate-400">{when(turn.created_at)}</span>
          {turn.status === 'queued' && mine && (
            <span className="inline-flex items-center gap-1 text-[11px] text-amber-600 dark:text-amber-400">
              <Clock size={10} />
              {turn.delivered_at ? 'seen' : 'queued'}
            </span>
          )}
          {turn.status === 'proposed' && (
            <span className="text-[11px] text-brand-600 dark:text-brand-400">proposal ready</span>
          )}
        </div>
        {turn.body && (
          <p className="mt-0.5 whitespace-pre-wrap break-words text-sm text-slate-600 dark:text-slate-300">
            {turn.body}
          </p>
        )}
        {turn.anchors.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {turn.anchors.map((anchor) => (
              <AnchorPill key={anchor.ref} anchor={anchor} labels={labels} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function AgentThreadPanel({
  targetType,
  targetId,
  anchorLabels,
  pendingAnchors,
  onStageAnchor,
  onRemoveAnchor,
  onClearAnchors,
  selectedRef,
  onClose,
  onSent,
}: Props) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [intent, setIntent] = useState<Intent>('question')
  const [draft, setDraft] = useState('')
  const [anchorNote, setAnchorNote] = useState('')
  const scroller = useRef<HTMLDivElement>(null)

  const stageable =
    selectedRef && !pendingAnchors.some((anchor) => anchor.ref === selectedRef) ? selectedRef : null

  const stage = useCallback(() => {
    if (!stageable || !anchorNote.trim()) return
    onStageAnchor({ ref: stageable, note: anchorNote.trim() })
    setAnchorNote('')
  }, [stageable, anchorNote, onStageAnchor])

  const threadKey = ['agent-thread', targetType, targetId]
  const { data: thread, isLoading, error } = useQuery<AgentThread>({
    queryKey: threadKey,
    queryFn: () => agentThreads.open(targetType, targetId),
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: true,
  })

  const turns = useMemo(() => thread?.turns ?? [], [thread])

  useEffect(() => {
    // Keep the newest turn in view, the way any chat surface behaves.
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [turns.length])

  const post = useMutation({
    mutationFn: async () => {
      if (!thread) throw new Error('conversation is not open yet')
      return agentThreads.postTurn(thread.id, {
        intent,
        body: draft.trim(),
        anchors: pendingAnchors,
      })
    },
    onSuccess: () => {
      setDraft('')
      onClearAnchors()
      onSent?.()
      void queryClient.invalidateQueries({ queryKey: threadKey })
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'could not queue that turn'
      toast.error(detail)
    },
  })

  const canSend = (draft.trim().length > 0 || pendingAnchors.length > 0) && !post.isPending

  const submit = useCallback(() => {
    if (canSend) post.mutate()
  }, [canSend, post])

  const ended = thread?.status === 'ended'
  const proposal = thread?.open_proposal ?? null

  return (
    <div className="flex h-full flex-col border-l border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950">
      <header className="flex items-center justify-between gap-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-slate-900 dark:text-white">
            {thread?.target_label ?? (targetType === 'workflow' ? 'Campaign' : 'View')}
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Ask anything. Instructions come back as a proposal you approve.
          </p>
        </div>
        <Button variant="ghost" size="xs" icon={X} onClick={onClose} aria-label="Close conversation" />
      </header>

      {proposal && (
        <div className="flex items-start gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200">
          <ShieldAlert size={14} className="mt-0.5 shrink-0" />
          <span>
            A proposal is open ({proposal.status}). New instructions queue behind it until it is
            applied or discarded — questions still go through immediately.
          </span>
        </div>
      )}

      <div ref={scroller} className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {isLoading && (
          <p className="flex items-center gap-2 text-xs text-slate-400">
            <Loader2 size={13} className="animate-spin" /> opening the conversation…
          </p>
        )}
        {error && (
          <p className="text-xs text-rose-600 dark:text-rose-400">
            {(error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
              'could not open this conversation'}
          </p>
        )}
        {!isLoading && turns.length === 0 && (
          <div className="rounded-lg border border-dashed border-slate-200 px-3 py-6 text-center dark:border-slate-800">
            <User size={18} className="mx-auto mb-2 text-slate-300 dark:text-slate-600" />
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Nothing here yet. Pin a{' '}
              {targetType === 'workflow' ? 'step on the canvas' : 'widget'} and ask what it does, or
              give an instruction to change it.
            </p>
          </div>
        )}
        {turns.map((turn) => (
          <TurnBubble key={turn.id} turn={turn} labels={anchorLabels} />
        ))}
      </div>

      <div className="border-t border-slate-200 px-4 py-3 dark:border-slate-800">
        {stageable && !ended && (
          <div className="mb-2 rounded-md border border-brand-200 bg-brand-50/60 p-2 dark:border-brand-900/60 dark:bg-brand-950/25">
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-brand-800 dark:text-brand-200">
              <MapPin size={11} />
              Pin “{label(anchorLabels, stageable)}” to this message
            </p>
            <div className="flex gap-1.5">
              <input
                value={anchorNote}
                onChange={(event) => setAnchorNote(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    stage()
                  }
                }}
                placeholder="what about it?"
                className="flex-1 rounded border border-slate-200 bg-white px-2 py-1 text-xs text-slate-800 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              />
              <Button size="xs" variant="secondary" onClick={stage} disabled={!anchorNote.trim()}>
                Pin
              </Button>
            </div>
          </div>
        )}

        {pendingAnchors.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {pendingAnchors.map((anchor) => (
              <AnchorPill
                key={anchor.ref}
                anchor={anchor}
                labels={anchorLabels}
                onRemove={() => onRemoveAnchor(anchor.ref)}
              />
            ))}
          </div>
        )}

        <div className="mb-2 inline-flex rounded-md border border-slate-200 p-0.5 dark:border-slate-700">
          {(
            [
              ['question', 'Ask', CircleHelp, 'Answered here. Never changes anything.'],
              ['instruction', 'Instruct', PencilLine, 'Comes back as a proposal you apply.'],
            ] as const
          ).map(([value, text, Icon, title]) => (
            <button
              key={value}
              type="button"
              title={title}
              onClick={() => setIntent(value)}
              className={`inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs transition ${
                intent === value
                  ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                  : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200'
              }`}
            >
              <Icon size={12} />
              {text}
            </button>
          ))}
        </div>

        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                event.preventDefault()
                submit()
              }
            }}
            rows={2}
            disabled={ended}
            placeholder={
              ended
                ? 'This conversation has ended.'
                : intent === 'question'
                  ? 'e.g. how many live leads are sitting on this step?'
                  : 'e.g. add a 2-day delay before the follow-up DM'
            }
            className="min-h-[42px] flex-1 resize-y rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:border-brand-400 focus:outline-none focus:ring-1 focus:ring-brand-300 disabled:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:disabled:bg-slate-900/50"
          />
          <Button
            size="sm"
            icon={Send}
            onClick={submit}
            disabled={!canSend || ended}
            isLoading={post.isPending}
          >
            Send
          </Button>
        </div>
        <p className="mt-1.5 text-[11px] text-slate-400">⌘/Ctrl + Enter to send</p>
      </div>
    </div>
  )
}
