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
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-rose-200'}`}>
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

export const ActionNode = ({ data, id, selected }: NodeProps) => {
  const nodeType = data.node_type as NodeType
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)
  const mode = (data as any).mode || 'simple'
  const configured = !!(data.email_account_id || data.voice_agent_id || nodeType === 'action_linkedin_invite' || (data.template && (data.template as any).body) || data.variable_name)
  const isEnrich = nodeType === 'action_enrich'
  
  return (
    <div className={`relative min-w-[220px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : cfg?.border ?? 'border-slate-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
      
      <div className="flex items-center justify-between mb-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${cfg?.bg ?? 'bg-slate-50'} ${cfg?.color ?? 'text-slate-500'}`}>
          {cfg?.icon}
        </div>
        <div className="flex rounded-lg bg-slate-50 p-0.5 ring-1 ring-slate-900/5 scale-90 origin-right">
          <div className={`px-2 py-0.5 text-[8px] font-black uppercase tracking-widest rounded-md transition-all ${mode !== 'flow' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-400'}`}>Simple</div>
          <div className={`px-2 py-0.5 text-[8px] font-black uppercase tracking-widest rounded-md transition-all ${mode === 'flow' ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-400'}`}>Flow</div>
        </div>
      </div>

      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{isEnrich ? 'Intelligence' : 'Engagement'}</p>
        <p className="text-xs font-bold text-slate-900">{cfg?.label ?? nodeType}</p>
      </div>

      {mode === 'flow' && (
        <div className="mt-3 flex items-center gap-1.5 rounded-lg border border-dashed border-sky-200 bg-sky-50/50 p-2">
          <Zap size={10} className="text-sky-500" />
          <span className="text-[9px] font-bold uppercase tracking-tight text-sky-600">Nested Architecture</span>
        </div>
      )}

      {isEnrich ? (
        <div className="mt-4 grid grid-cols-2 divide-x divide-slate-50 border-t border-slate-50 pt-3">
          <div className="flex flex-col items-center">
            <span className="text-[9px] font-black uppercase text-emerald-500">Found</span>
            <Handle type="source" id="found" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-emerald-400" />
          </div>
          <div className="flex flex-col items-center">
            <span className="text-[9px] font-black uppercase text-rose-400">Empty</span>
            <Handle type="source" id="not_found" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!mt-1 !h-2 !w-2 !border-none !bg-rose-400" />
          </div>
        </div>
      ) : (
        <>
          <div className="mt-3 flex items-center justify-between border-t border-slate-50 pt-3">
            <span className={`text-[10px] font-medium ${configured ? 'text-emerald-500' : 'text-slate-300'}`}>
              {configured ? 'Ready' : 'Draft'}
            </span>
            <Settings2 size={12} className="text-slate-300" />
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
    <div className={`relative min-w-[180px] rounded-xl border-2 bg-slate-900 p-4 shadow-lg transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-slate-800'}`}>
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
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : cfg?.border ?? 'border-amber-200'}`}>
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
  <div className={`relative min-w-[260px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-violet-200'}`}>
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
    <div className={`relative min-w-[220px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-teal-200'}`}>
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
  <div className={`relative min-w-[160px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-slate-200'}`}>
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
  <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-orange-200'}`}>
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
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-purple-200'}`}>
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
  <div className={`relative min-w-[180px] rounded-xl border-2 bg-emerald-50 p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-emerald-200'}`}>
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
  <div className={`relative min-w-[160px] rounded-xl border-2 bg-rose-50 p-4 text-center shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-rose-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <p className="text-[10px] font-bold uppercase tracking-widest text-rose-500">Terminal</p>
    <p className="text-sm font-extrabold tracking-tight text-rose-700">End Sequence</p>
  </div>
)

export const ParallelForkNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[260px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-amber-200'}`}>
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
