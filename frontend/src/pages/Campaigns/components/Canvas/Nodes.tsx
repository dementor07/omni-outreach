import React from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Handle, Position, NodeProps, Node } from '@xyflow/react'
import { Linkedin, Mail, MessageSquare, Instagram, Send, Phone, Clock, Zap, Tag, MinusCircle, GitBranch, Bell, StopCircle, Shuffle, Webhook, MessageCircle, Brain, Route, Database, Flame, UserCheck, Radio, Settings2 } from 'lucide-react'
import { api } from '../../../../api/client'
import { NodeType } from '../../../../hooks/useSequenceSteps'
import { NODE_PALETTE } from '../../constants'

export const EventNode = ({ data, selected }: NodeProps) => {
  const nodeType = data.node_type as NodeType
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)
  
  return (
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-rose-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
      <div className="flex items-center gap-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg bg-rose-50 text-rose-500`}>
          {cfg?.icon ?? <Bell size={14} />}
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-rose-500/60">Listener Event</p>
          <p className="text-xs font-bold text-slate-900">{cfg?.label ?? nodeType}</p>
        </div>
      </div>
      <div className="mt-4 flex items-center justify-center border-t border-slate-50 pt-3">
        <span className="text-[9px] font-black uppercase text-rose-500">Trigger</span>
        <Handle type="source" position={Position.Bottom} className="!static !ml-2 !h-2 !w-2 !border-none !bg-rose-400" />
      </div>
    </div>
  )
}

// Category labels (uppercase eyebrow) — distinct per node family so AI Compose
// doesn't read as "Engagement". Maps category -> the small eyebrow text.
const CATEGORY_EYEBROW: Record<string, string> = {
  linkedin: 'LinkedIn',
  messaging: 'Messaging',
  intelligence: 'Intelligence',
  tag: 'Tagging',
  webhook: 'Integration',
  alert: 'Alert',
  voice: 'AI Voice',
  enrich: 'Enrichment',
  flow: 'Control',
}

// Trim a string for compact preview display in the card body.
function preview(s: unknown, max = 60): string {
  if (typeof s !== 'string') return ''
  const t = s.trim().replace(/\s+/g, ' ')
  return t.length > max ? t.slice(0, max - 1) + '…' : t
}

export const ActionNode = ({ data, selected }: NodeProps) => {
  const nodeType = data.node_type as NodeType
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)
  const category = cfg?.category ?? 'messaging'
  const d = data as Record<string, unknown>

  // Per-category "ready" check + body content
  let bodyPreview: React.ReactNode = null
  let configured = false

  if (category === 'intelligence' && nodeType === 'action_ai_compose') {
    const instruction = preview(d.instruction, 90)
    const targetVar = (d.target_variable as string) || 'ai_draft'
    const channel = (d.channel as string) || 'email'
    configured = !!instruction
    bodyPreview = (
      <div className="mt-2 space-y-1.5">
        <div className="rounded-md bg-fuchsia-50/70 px-2 py-1.5 text-[11px] italic text-fuchsia-900 dark:bg-fuchsia-900/20 dark:text-fuchsia-200">
          {instruction || <span className="text-slate-400 not-italic">No instruction set</span>}
        </div>
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-slate-500">→ <code className="font-mono text-fuchsia-700">{`{{${targetVar}}}`}</code></span>
          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono uppercase tracking-wide text-slate-600 dark:bg-slate-800 dark:text-slate-300">{channel}</span>
        </div>
      </div>
    )
  } else if (category === 'intelligence' && nodeType === 'action_data_transform') {
    const varName = (d.variable_name as string) || ''
    const prompt = preview(d.prompt, 80)
    configured = !!varName && !!prompt
    bodyPreview = (
      <div className="mt-2 space-y-1.5">
        <div className="rounded-md bg-emerald-50/70 px-2 py-1.5 text-[11px] italic text-emerald-900 dark:bg-emerald-900/20 dark:text-emerald-200">
          {prompt || <span className="text-slate-400 not-italic">No prompt set</span>}
        </div>
        <div className="text-[10px] text-slate-500">→ <code className="font-mono text-emerald-700">{`{{${varName || 'variable_name'}}}`}</code></div>
      </div>
    )
  } else if (category === 'enrich') {
    const source = (d.enrich_source as string) || ''
    configured = !!source
    bodyPreview = (
      <div className="mt-2 text-[11px] text-slate-600 dark:text-slate-400">
        Source: <span className="font-semibold text-slate-900 dark:text-white">{source || 'not set'}</span>
      </div>
    )
  } else if (category === 'tag') {
    const tag = (d.tag as string) || ''
    configured = !!tag
    bodyPreview = (
      <div className="mt-2">
        {tag ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300">
            <Tag size={10} />{tag}
          </span>
        ) : <span className="text-[11px] italic text-slate-400">No tag set</span>}
      </div>
    )
  } else if (category === 'alert') {
    const title = preview(d.title, 50) || 'Hot Lead Alert'
    const channels = (d.channel_ids as string[] | undefined) || []
    configured = true
    bodyPreview = (
      <div className="mt-2 space-y-1.5">
        <div className="flex items-start gap-1.5 text-[11px] text-rose-900 dark:text-rose-200">
          <Bell size={11} className="mt-0.5 shrink-0" />
          <span className="font-semibold">{title}</span>
        </div>
        <div className="text-[10px] text-slate-500">{channels.length ? `→ ${channels.length} channel${channels.length === 1 ? '' : 's'}` : '→ all active channels'}</div>
      </div>
    )
  } else if (category === 'webhook') {
    const url = preview(d.url, 50)
    const method = (d.method as string) || 'POST'
    configured = !!url
    bodyPreview = (
      <div className="mt-2 flex items-center gap-1.5 text-[10px]">
        <span className="rounded bg-slate-900 px-1.5 py-0.5 font-mono text-white">{method}</span>
        <span className="truncate font-mono text-slate-600 dark:text-slate-400">{url || 'no url'}</span>
      </div>
    )
  } else if (category === 'voice') {
    const agent = (d.voice_agent_id as string) || ''
    const mode = (d.mode as string) || 'simple'
    configured = !!agent
    bodyPreview = (
      <div className="mt-2 space-y-1.5">
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-slate-500">{agent ? 'Agent linked' : 'No agent'}</span>
          <span className={`rounded px-1.5 py-0.5 font-mono uppercase tracking-wide ${mode === 'flow' ? 'bg-indigo-100 text-indigo-700' : 'bg-slate-100 text-slate-600'}`}>{mode}</span>
        </div>
      </div>
    )
  } else if (category === 'linkedin' || category === 'messaging') {
    // Delivery channels — show subject/body preview from the linked template
    const tpl = (d.template as Record<string, unknown> | undefined) || {}
    const body = preview((tpl.body as string) ?? d.body, 80)
    const subject = preview((tpl.subject as string) ?? d.subject, 40)
    const acctLinked = !!(d.email_account_id || d.linkedin_account_id || nodeType === 'action_linkedin_invite')
    configured = !!body && acctLinked
    bodyPreview = (
      <div className="mt-2 space-y-1">
        {subject && <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{subject}</div>}
        <div className={`rounded-md px-2 py-1.5 text-[11px] italic ${body ? 'bg-slate-50 text-slate-700 dark:bg-slate-800/50 dark:text-slate-300' : 'text-slate-400'}`}>
          {body || 'No message body'}
        </div>
      </div>
    )
  }

  // Simple/Flow toggle: ONLY meaningful for voice (Retell nested-flow vs simple-llm).
  // For every other action node it was visual noise.
  const showFlowToggle = nodeType === 'action_voice'
  const flowMode = showFlowToggle ? ((d.mode as string) || 'simple') : null

  return (
    <div className={`relative min-w-[240px] rounded-xl border-2 bg-white p-3.5 shadow-sm transition-all dark:bg-slate-900 ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : cfg?.border ?? 'border-slate-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />

      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${cfg?.bg ?? 'bg-slate-50'} ${cfg?.color ?? 'text-slate-500'}`}>
            {cfg?.icon}
          </div>
          <div>
            <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">{CATEGORY_EYEBROW[category] ?? 'Action'}</p>
            <p className="text-[13px] font-bold text-slate-900 dark:text-white">{cfg?.label ?? nodeType}</p>
          </div>
        </div>
        {showFlowToggle && (
          <div className="flex rounded-lg bg-slate-50 p-0.5 ring-1 ring-slate-900/5 dark:bg-slate-800 dark:ring-white/10">
            <div className={`px-1.5 py-0.5 text-[8px] font-black uppercase tracking-widest rounded transition-all ${flowMode !== 'flow' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white' : 'text-slate-400'}`}>Simple</div>
            <div className={`px-1.5 py-0.5 text-[8px] font-black uppercase tracking-widest rounded transition-all ${flowMode === 'flow' ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-400'}`}>Flow</div>
          </div>
        )}
      </div>

      {bodyPreview}

      {category === 'enrich' ? (
        <div className="mt-3 grid grid-cols-2 divide-x divide-slate-50 border-t border-slate-50 pt-2 dark:divide-slate-800 dark:border-slate-800">
          <div className="flex flex-col items-center gap-1">
            <span className="text-[9px] font-black uppercase tracking-wide text-emerald-500">Found</span>
            <Handle type="source" id="found" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!h-2 !w-2 !border-none !bg-emerald-400" />
          </div>
          <div className="flex flex-col items-center gap-1">
            <span className="text-[9px] font-black uppercase tracking-wide text-rose-400">Empty</span>
            <Handle type="source" id="not_found" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!h-2 !w-2 !border-none !bg-rose-400" />
          </div>
        </div>
      ) : (
        <>
          <div className="mt-2.5 flex items-center justify-between border-t border-slate-50 pt-2 dark:border-slate-800">
            <span className={`text-[10px] font-medium ${configured ? 'text-emerald-500' : 'text-slate-300'}`}>
              {configured ? 'Ready' : 'Draft'}
            </span>
            <Settings2 size={11} className="text-slate-300" />
          </div>
          <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-slate-300" />
        </>
      )}
    </div>
  )
}

export const TriggerNode = ({ selected, data }: NodeProps) => {
  const { id: campaignId } = useParams()
  const navigate = useNavigate()
  const live = Boolean((data as any)?.live)
  const sourcesRecent = ((data as any)?.sources_recent || {}) as Record<string, number>
  const liveTotal = Object.values(sourcesRecent).reduce((a, b) => a + (b || 0), 0)
  const configsQuery = useQuery<Array<{ id: string; source_type: string; source_display_name: string; cron_schedule: string | null }>>({
    queryKey: ['lead-gen-configs', campaignId],
    queryFn: () => api.get(`/lead-gen/configs/${campaignId}`).then(r => r.data),
    enabled: !!campaignId,
    staleTime: 30_000,
  })
  const configs = configsQuery.data || []
  const sourceCount = configs.length
  const scheduledCount = configs.filter(c => c.cron_schedule).length

  return (
    <div className={`relative min-w-[180px] rounded-xl border-2 bg-slate-900 p-4 shadow-lg transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-slate-800'}`}>
      <div className="flex items-center gap-3 text-white">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/20">
          <Zap size={14} fill="currentColor" />
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Trigger</p>
          <p className="text-xs font-bold uppercase tracking-tight">Sequence Start</p>
        </div>
      </div>
      {campaignId && (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); navigate('/lead-sources') }}
          title="Open Lead Sources"
          className="mt-3 flex w-full items-center justify-between rounded-lg bg-white/5 px-2.5 py-1.5 text-[10px] font-semibold text-white/80 ring-1 ring-white/10 hover:bg-white/10 transition-colors nodrag"
        >
          <span className="flex items-center gap-1.5">
            <Database size={10} />
            {sourceCount === 0 ? 'No sources' : `${sourceCount} source${sourceCount > 1 ? 's' : ''}`}
          </span>
          {scheduledCount > 0 && (
            <span className="flex items-center gap-1 text-emerald-300">
              <Clock size={10} /> {scheduledCount}
            </span>
          )}
        </button>
      )}
      {live && liveTotal > 0 && (
        <div className="mt-2 space-y-1 rounded-lg bg-emerald-500/10 px-2.5 py-1.5 ring-1 ring-emerald-500/20">
          <p className="text-[9px] font-bold uppercase tracking-widest text-emerald-300 flex items-center gap-1">
            <Radio size={9} className="animate-pulse" /> +{liveTotal} in 60s
          </p>
          {Object.entries(sourcesRecent).slice(0, 4).map(([source, count]) => (
            <div key={source} className="flex items-center justify-between text-[10px] text-emerald-100/80">
              <span className="truncate">{source}</span>
              <span className="font-bold">{count}</span>
            </div>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-white/20" />
    </div>
  )
}

export const ConditionNode = ({ data, selected }: NodeProps) => {
  const nodeType = data.node_type as NodeType
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)

  return (
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : cfg?.border ?? 'border-amber-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
      <div className="flex items-center gap-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${cfg?.bg ?? 'bg-amber-50'} ${cfg?.color ?? 'text-amber-500'}`}>
          {cfg?.icon ?? <GitBranch size={14} />}
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Condition</p>
          <p className="text-xs font-bold text-slate-900">{cfg?.label ?? 'Condition'}</p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 divide-x divide-slate-50 border-t border-slate-50 pt-3">
        <div className="flex flex-col items-center">
          <span className="text-[9px] font-black uppercase text-emerald-500">True</span>
          <Handle type="source" id="true" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-emerald-400" />
        </div>
        <div className="flex flex-col items-center">
          <span className="text-[9px] font-black uppercase text-rose-400">False</span>
          <Handle type="source" id="false" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-rose-400" />
        </div>
      </div>
    </div>
  )
}

const REPLY_INTENT_HANDLES: { id: string; label: string; color: string; dot: string }[] = [
  { id: 'positive',      label: 'Positive',     color: 'text-emerald-500', dot: '!bg-emerald-400' },
  { id: 'negative',      label: 'Negative',     color: 'text-rose-500',    dot: '!bg-rose-400' },
  { id: 'neutral',       label: 'Neutral',      color: 'text-slate-500',   dot: '!bg-slate-400' },
  { id: 'out_of_office', label: 'OOO',          color: 'text-amber-500',   dot: '!bg-amber-400' },
  { id: 'unsubscribe',   label: 'Unsubscribe',  color: 'text-fuchsia-500', dot: '!bg-fuchsia-400' },
  { id: 'bounce',        label: 'Bounce',       color: 'text-orange-500',  dot: '!bg-orange-400' },
]

export const ReplyIntentNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[260px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-violet-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-50 text-violet-600">
        <Brain size={14} />
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Condition</p>
        <p className="text-xs font-bold text-slate-900">Reply Intent</p>
      </div>
    </div>
    <div className="mt-4 grid grid-cols-3 gap-x-3 gap-y-2 border-t border-slate-50 pt-3">
      {REPLY_INTENT_HANDLES.map(h => (
        <div key={h.id} className="flex flex-col items-center">
          <span className={`text-[9px] font-black uppercase ${h.color}`}>{h.label}</span>
          <Handle
            type="source"
            id={h.id}
            position={Position.Bottom}
            style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }}
            className={`!mt-1 !h-2 !w-2 !border-none ${h.dot}`}
          />
        </div>
      ))}
    </div>
  </div>
)

export const HumanApprovalNode = ({ data, selected }: NodeProps) => {
  const title = (data as any)?.title || 'Awaiting human approval'
  return (
    <div className={`relative min-w-[220px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-teal-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 text-teal-600">
          <UserCheck size={14} />
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Approval</p>
          <p className="text-xs font-bold text-slate-900 truncate max-w-[160px]">{title}</p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 divide-x divide-slate-50 border-t border-slate-50 pt-3">
        <div className="flex flex-col items-center">
          <span className="text-[9px] font-black uppercase text-emerald-500">Approve</span>
          <Handle type="source" id="approve" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-emerald-400" />
        </div>
        <div className="flex flex-col items-center">
          <span className="text-[9px] font-black uppercase text-rose-400">Reject</span>
          <Handle type="source" id="reject" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-rose-400" />
        </div>
      </div>
    </div>
  )
}

export const DelayNode = ({ data, id, selected }: NodeProps<Node<{ delay_value?: number; delay_days?: number; delay_unit?: string; onChange?: (id: string, val: number) => void }>>) => (
  <div className={`relative min-w-[160px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-slate-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Clock size={14} className="text-slate-400" />
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Wait</span>
      </div>
      <div className="flex items-center gap-1">
        <span className="text-xs font-bold text-slate-900">{data.delay_value || data.delay_days || 1}</span>
        <span className="text-[10px] font-bold text-slate-400 uppercase">{data.delay_unit || 'Days'}</span>
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-slate-300" />
  </div>
)

export const WaitUntilNode = ({ data, id, selected }: NodeProps<Node<{ wait_until_date?: string; wait_until_time?: string; onChange?: (id: string, field: string, val: string) => void }>>) => (
  <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-orange-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center gap-2 mb-2">
      <Clock size={14} className="text-orange-500" />
      <span className="text-[10px] font-bold uppercase tracking-widest text-orange-500">Wait Until</span>
    </div>
    <div className="space-y-1.5">
      <div className="text-[10px] font-mono text-slate-600 bg-slate-50 px-2 py-1 rounded border border-slate-100">
        {data.wait_until_date || 'No date'} at {data.wait_until_time || '09:00'}
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-slate-300" />
  </div>
)

export const SplitNode = ({ data, selected }: NodeProps) => {
  const weights = (data as any)?.weights
  const tA = weights?.true?.alpha ?? 1
  const tB = weights?.true?.beta ?? 1
  const fA = weights?.false?.alpha ?? 1
  const fB = weights?.false?.beta ?? 1
  const hasLearned = weights && (tA + tB + fA + fB) > 4
  const trueRate = Math.round((tA / (tA + tB)) * 100)
  const falseRate = Math.round((fA / (fA + fB)) * 100)

  return (
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-purple-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-purple-50 text-purple-600">
          <Shuffle size={14} />
        </div>
        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-purple-600/60">Control · AI Split</p>
          <p className="text-xs font-bold text-slate-900">{hasLearned ? 'Bandit Active' : 'Learning (50/50)'}</p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 divide-x divide-slate-50 border-t border-slate-50 pt-3">
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[9px] font-black uppercase text-purple-500">Path A</span>
          {hasLearned && <span className="text-[9px] font-bold text-emerald-600">{trueRate}% win rate</span>}
          <Handle type="source" id="true" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-purple-400" />
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[9px] font-black uppercase text-purple-500">Path B</span>
          {hasLearned && <span className="text-[9px] font-bold text-emerald-600">{falseRate}% win rate</span>}
          <Handle type="source" id="false" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-purple-400" />
        </div>
      </div>
    </div>
  )
}

export const GoalNode = ({ data, selected }: NodeProps) => (
  <div className={`relative min-w-[180px] rounded-xl border-2 bg-emerald-50 p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-emerald-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center gap-2 mb-1">
      <Zap size={14} className="text-emerald-600" />
      <span className="text-[10px] font-bold uppercase tracking-widest text-emerald-500">Conversion Goal</span>
    </div>
    <p className="text-xs font-bold text-slate-900">{(data as any).goal_name || 'Meeting booked'}</p>
    <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-slate-300" />
  </div>
)

export const EndNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[160px] rounded-xl border-2 bg-rose-50 p-4 text-center shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-rose-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <p className="text-[10px] font-bold uppercase tracking-widest text-rose-500">Terminal</p>
    <p className="text-sm font-extrabold tracking-tight text-rose-700">End Sequence</p>
  </div>
)

export const ParallelForkNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[260px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-brand-500 ring-4 ring-brand-500/10' : 'border-amber-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
        <GitBranch size={14} />
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Control</p>
        <p className="text-xs font-bold text-slate-900">Parallel Fork</p>
      </div>
    </div>
    <p className="mt-2 text-[10px] text-slate-500 italic">Fires all branches simultaneously.</p>
    <div className="mt-4 grid grid-cols-5 gap-1 border-t border-slate-50 pt-3">
      {[1, 2, 3, 4, 5].map(i => (
        <div key={i} className="flex flex-col items-center">
          <span className="text-[8px] font-black text-slate-300">B{i}</span>
          <Handle
            type="source"
            id={`branch_${i}`}
            position={Position.Bottom}
            style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }}
            className="!mt-1 !h-2 !w-2 !border-none !bg-amber-400"
          />
        </div>
      ))}
    </div>
  </div>
)

export const nodeTypes = {
  trigger_start: TriggerNode,
  action_linkedin_invite: ActionNode,
  action_linkedin_dm: ActionNode,
  action_linkedin_inmail: ActionNode,
  action_linkedin_profile_view: ActionNode,
  action_add_tag: ActionNode,
  action_remove_tag: ActionNode,
  action_email: ActionNode,
  action_whatsapp: ActionNode,
  action_instagram: ActionNode,
  action_telegram: ActionNode,
  action_voice: ActionNode,
  action_sms: ActionNode,
  action_webhook: ActionNode,
  action_enrich: ActionNode,
  action_data_transform: ActionNode,
  action_ai_compose: ActionNode,
  action_hot_lead_alert: ActionNode,
  control_parallel_fork: ParallelForkNode,
  human_approval: HumanApprovalNode,
  condition_reply_intent: ReplyIntentNode,
  condition_replied: ConditionNode,
  condition_linkedin_distance: ConditionNode,
  condition_tag_exists: ConditionNode,
  condition_ai_screen: ConditionNode,
  condition_lead_source: ConditionNode,
  condition_has_field: ConditionNode,
  event_invite_accepted: EventNode,
  event_email_opened: EventNode,
  event_link_clicked: EventNode,
  delay: DelayNode,
  wait_until: WaitUntilNode,
  split: SplitNode,
  goal: GoalNode,
  end: EndNode,
}
