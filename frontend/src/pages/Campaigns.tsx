import { FormEvent, useEffect, useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Link, useNavigate, useParams, useSearchParams, useLocation } from 'react-router-dom'
import { Plus, Save, Mail, Linkedin, Phone, MessageSquare, Instagram, Send, Clock, Zap, X, ChevronRight, Settings2, Trash2, Radio } from 'lucide-react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  Edge,
  Node,
  Handle,
  Position,
  NodeProps,
  Panel,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useReactFlow,
  MarkerType,
  ConnectionLineType,
  type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'
import SequentialBuilder from '../components/SequentialBuilder'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/time'
import {
  CampaignPayload,
  useCampaignStats,
  useCreateCampaign,
  useDeleteCampaign,
  useGetCampaign,
  useListCampaigns,
  useUpdateCampaign,
} from '../hooks/useCampaigns'
import { useImportLeads, useListLeads } from '../hooks/useLeads'
import { useQueueList } from '../hooks/useQueue'
import {
  useGetGraph,
  useSaveGraph,
  useGetTemplate,
  useUpsertTemplate,
  type NodeType,
} from '../hooks/useSequenceSteps'

type CampaignTab = 'leads' | 'queue' | 'sequence' | 'settings'

interface RetellPrompt {
  begin_message: string;
  general_prompt: string;
  llm_id: string;
  model: string;
}

const defaultCampaignForm: CampaignPayload = {
  name: '',
  daily_lead_cap: 50,
  invite_daily_cap: 20,
  simulation_mode: false,
  timezone: 'Asia/Kolkata',
  active_hours_start: 9,
  active_hours_end: 18,
  screening_prompt: '',
  sequence_mode: 'sequential',
}

// ── Custom deletable edge ──────────────────────────────────────────────────

function CustomEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected }: EdgeProps) {
  const { deleteElements } = useReactFlow()
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: selected ? '#0ea5e9' : '#e2e8f0', strokeWidth: selected ? 3 : 2 }} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="nodrag nopan"
        >
          <button
            onClick={(e) => { e.stopPropagation(); deleteElements({ edges: [{ id }] }) }}
            style={{ display: selected ? 'flex' : 'none' }}
            className="h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-[11px] font-bold text-slate-400 shadow-sm transition hover:text-rose-500"
          >
            ×
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

function TelemetryEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected, data }: EdgeProps) {
  const { deleteElements } = useReactFlow()
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })

  const activity = (data?.activity as number) || 0
  const backpressure = (data?.backpressure as number) || 0

  const strokeColor = backpressure > 5
    ? '#f59e0b'
    : activity >= 10 ? '#10b981'
    : activity >= 4 ? '#38bdf8'
    : activity >= 1 ? '#7dd3fc'
    : selected ? '#0ea5e9'
    : '#e2e8f0'
  const strokeWidth = selected ? 3 : 2 + Math.min(activity * 0.4, 3)
  const strokeDasharray = backpressure > 5 ? '6 3' : undefined

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: strokeColor, strokeWidth, strokeDasharray, transition: 'stroke 0.8s, stroke-width 0.8s' }} />
      <EdgeLabelRenderer>
        <div style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`, pointerEvents: 'all' }} className="nodrag nopan flex items-center gap-1">
          {activity > 0 && (
            <span className="rounded-full bg-emerald-500 px-1.5 py-0.5 text-[9px] font-black text-white shadow-sm">
              {activity}
            </span>
          )}
          {backpressure > 5 && (
            <span className="rounded-full bg-amber-400 px-1.5 py-0.5 text-[9px] font-black text-white shadow-sm">
              ⏳{backpressure}
            </span>
          )}
          <button
            onClick={(e) => { e.stopPropagation(); deleteElements({ edges: [{ id }] }) }}
            style={{ display: selected ? 'flex' : 'none' }}
            className="h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-[11px] font-bold text-slate-400 shadow-sm transition hover:text-rose-500"
          >
            ×
          </button>
        </div>
      </EdgeLabelRenderer>
    </>
  )
}

const edgeTypes = { custom: CustomEdge, telemetry: TelemetryEdge }

const defaultEdgeOptions = {
  type: 'custom',
  markerEnd: { type: MarkerType.ArrowClosed, color: '#cbd5e1', width: 20, height: 20 },
}

// ── Node palette config ────────────────────────────────────────────────────

const NODE_PALETTE: { type: NodeType; label: string; icon: React.ReactNode; color: string; bg: string; border: string }[] = [
  { type: 'action_linkedin_invite', label: 'LinkedIn Invite', icon: <Linkedin size={15} />, color: 'text-sky-600',     bg: 'bg-sky-50',     border: 'border-sky-200' },
  { type: 'action_linkedin_dm',     label: 'LinkedIn DM',     icon: <Linkedin size={15} />, color: 'text-sky-500',     bg: 'bg-sky-50',     border: 'border-sky-200' },
  { type: 'action_linkedin_inmail', label: 'LinkedIn InMail', icon: <Linkedin size={15} />, color: 'text-indigo-500',  bg: 'bg-indigo-50',  border: 'border-indigo-200' },
  { type: 'action_linkedin_profile_view', label: 'LinkedIn View Profile', icon: <Linkedin size={15} />, color: 'text-slate-500', bg: 'bg-slate-50', border: 'border-slate-200' },
  { type: 'action_email',           label: 'Email',           icon: <Mail size={15} />,     color: 'text-slate-600',   bg: 'bg-slate-50',   border: 'border-slate-200' },
  { type: 'action_whatsapp',        label: 'WhatsApp',        icon: <MessageSquare size={15} />, color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  { type: 'action_instagram',       label: 'Instagram',       icon: <Instagram size={15} />, color: 'text-pink-500',   bg: 'bg-pink-50',    border: 'border-pink-200' },
  { type: 'action_telegram',        label: 'Telegram',        icon: <Send size={15} />,     color: 'text-blue-500',    bg: 'bg-blue-50',    border: 'border-blue-200' },
  { type: 'action_voice',           label: 'Voice Call',      icon: <Phone size={15} />,    color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200' },
  { type: 'action_add_tag',         label: 'Add Tag',         icon: <Zap size={15} />,      color: 'text-slate-600',   bg: 'bg-slate-50',   border: 'border-slate-200' },
  { type: 'action_remove_tag',      label: 'Remove Tag',      icon: <Zap size={15} />,      color: 'text-slate-600',   bg: 'bg-slate-50',   border: 'border-slate-200' },
  { type: 'condition_replied',      label: 'Branch: Reply?',  icon: <Zap size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'condition_linkedin_distance', label: 'Branch: Connection Distance', icon: <Zap size={15} />, color: 'text-amber-600', bg: 'bg-amber-50', border: 'border-amber-200' },
  { type: 'condition_tag_exists',   label: 'Branch: Has Tag?',icon: <Zap size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'event_invite_accepted',  label: 'Event: Invite Accepted', icon: <Zap size={15} />, color: 'text-rose-500',   bg: 'bg-rose-50',   border: 'border-rose-200' },
  { type: 'event_email_opened',     label: 'Event: Email Opened', icon: <Zap size={15} />, color: 'text-rose-500',   bg: 'bg-rose-50',   border: 'border-rose-200' },
  { type: 'event_link_clicked',     label: 'Event: Link Clicked', icon: <Zap size={15} />, color: 'text-rose-500',   bg: 'bg-rose-50',   border: 'border-rose-200' },
  { type: 'delay',                  label: 'Wait / Delay',    icon: <Clock size={15} />,    color: 'text-slate-400',   bg: 'bg-slate-50',   border: 'border-slate-200' },
  { type: 'split',                  label: 'A/B Split',       icon: <Zap size={15} />,      color: 'text-purple-600',  bg: 'bg-purple-50',  border: 'border-purple-200' },
  { type: 'end',                    label: 'End Sequence',    icon: <Zap size={15} />,      color: 'text-rose-600',    bg: 'bg-rose-50',    border: 'border-rose-400' },
]

// ── React Flow Node Types ──────────────────────────────────────────────────

const EventNode = ({ data, selected }: NodeProps) => {
  const nodeType = data.node_type as NodeType
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)
  
  return (
    <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-rose-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
      <div className="flex items-center gap-3">
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg bg-rose-50 text-rose-500`}>
          <Zap size={14} />
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

const ActionNode = ({ data, id, selected }: NodeProps) => {
  const nodeType = data.node_type as NodeType
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)
  const mode = (data as any).mode || 'simple'
  const configured = !!(data.email_account_id || data.voice_agent_id || nodeType === 'action_linkedin_invite' || (data.template && (data.template as any).body))
  
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
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Engagement</p>
        <p className="text-xs font-bold text-slate-900">{cfg?.label ?? nodeType}</p>
      </div>

      {mode === 'flow' && (
        <div className="mt-3 flex items-center gap-1.5 rounded-lg border border-dashed border-sky-200 bg-sky-50/50 p-2">
          <Zap size={10} className="text-sky-500" />
          <span className="text-[9px] font-bold uppercase tracking-tight text-sky-600">Nested Architecture</span>
        </div>
      )}

      <div className="mt-3 flex items-center justify-between border-t border-slate-50 pt-3">
        <span className={`text-[10px] font-medium ${configured ? 'text-emerald-500' : 'text-slate-300'}`}>
          {configured ? 'Ready' : 'Draft'}
        </span>
        <Settings2 size={12} className="text-slate-300" />
      </div>
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-slate-300" />
    </div>
  )
}

const TriggerNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[180px] rounded-xl border-2 bg-slate-900 p-4 shadow-lg transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-slate-800'}`}>
    <div className="flex items-center gap-3 text-white">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/20">
        <Zap size={14} fill="currentColor" />
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Inception</p>
        <p className="text-xs font-bold uppercase tracking-tight">Lead Accepted</p>
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-white/20" />
  </div>
)

const ConditionNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[200px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-amber-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center gap-3">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-50 text-amber-500">
        <Zap size={14} />
      </div>
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-amber-500/60">Condition</p>
        <p className="text-xs font-bold text-slate-900">Wait for Reply</p>
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

const DelayNode = ({ data, id, selected }: NodeProps<Node<{ delay_days?: number; onChange?: (id: string, val: number) => void }>>) => (
  <div className={`relative min-w-[160px] rounded-xl border-2 bg-white p-4 shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-slate-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Clock size={14} className="text-slate-400" />
        <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Wait</span>
      </div>
      <div className="flex items-center gap-1">
        <input 
          type="number"
          min="1"
          value={data.delay_days || 1}
          onChange={(e) => data.onChange?.(id, parseInt(e.target.value) || 1)}
          className="w-10 rounded border-none bg-slate-50 py-0.5 text-center text-xs font-bold text-slate-900 focus:ring-2 focus:ring-sky-500/20"
        />
        <span className="text-[10px] font-bold text-slate-400 uppercase">Days</span>
      </div>
    </div>
    <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-none !bg-slate-300" />
  </div>
)

const SplitNode = ({ data, selected }: NodeProps) => {
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
          <Zap size={14} />
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

const EndNode = ({ selected }: NodeProps) => (
  <div className={`relative min-w-[160px] rounded-xl border-2 bg-rose-50 p-4 text-center shadow-sm transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/10' : 'border-rose-200'}`}>
    <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-none !bg-slate-300" />
    <p className="text-[10px] font-bold uppercase tracking-widest text-rose-500">Terminal</p>
    <p className="text-sm font-extrabold tracking-tight text-rose-700">End Sequence</p>
  </div>
)

const nodeTypes = {
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
  condition_replied: ConditionNode,
  condition_linkedin_distance: ConditionNode,
  condition_tag_exists: ConditionNode,
  event_invite_accepted: EventNode,
  event_email_opened: EventNode,
  event_link_clicked: EventNode,
  delay: DelayNode,
  split: SplitNode,
  end: EndNode,
}

// ── Main Component ─────────────────────────────────────────────────────────

export default function Campaigns() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = (searchParams.get('tab') as CampaignTab | null) || 'leads'
  const toast = useToast()

  const campaignsQuery = useListCampaigns()
  const campaignQuery = useGetCampaign(id)
  const statsQuery = useCampaignStats(id)
  const createCampaign = useCreateCampaign()
  const updateCampaign = useUpdateCampaign()
  const deleteCampaign = useDeleteCampaign()
  const importLeads = useImportLeads()
  const leadsQuery = useListLeads(id, 1, 50)
  const queueQuery = useQueueList({ campaignId: id, limit: 100 })
  
  const graphQuery = useGetGraph(id)
  const saveGraph = useSaveGraph()

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [liveMode, setLiveMode] = useState(false)
  const [telemetry, setTelemetry] = useState<{ activity: Record<string, number>; backpressure: Record<string, number> }>({ activity: {}, backpressure: {} })
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  
  const [createOpen, setCreateOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [form, setForm] = useState<CampaignPayload>(defaultCampaignForm)
  const [importPayload, setImportPayload] = useState('')

  const updateNodeData = useCallback((nodeId: string, newData: any) => {
    setNodes((nds) =>
      nds.map((node) => {
        if (node.id === nodeId) {
          return { ...node, data: { ...node.data, ...newData } }
        }
        return node
      })
    )
  }, [setNodes])

  // Sync React Flow state with database
  useEffect(() => {
    if (graphQuery.data) {
      const rfNodes: Node[] = graphQuery.data.nodes.map(n => ({
        id: n.id,
        type: n.node_type,
        position: { x: n.position_x, y: n.position_y },
        data: { 
          ...n.data, 
          node_type: n.node_type,
          onChange: (id: string, val: number) => updateNodeData(id, { delay_days: val })
        },
      }))
      const rfEdges: Edge[] = graphQuery.data.edges.map(e => ({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        sourceHandle: e.source_handle,
        targetHandle: e.target_handle,
        type: 'custom',
      }))
      setNodes(rfNodes)
      setEdges(rfEdges)
    }
  }, [graphQuery.data, setNodes, setEdges, updateNodeData])

  // Telemetry polling — runs when Live mode is on and sequence tab is active
  useEffect(() => {
    if (!liveMode || !id || activeTab !== 'sequence') return
    const poll = async () => {
      try {
        const { data } = await api.get<{ activity: Record<string, number>; backpressure: Record<string, number> }>(`/sequences/${id}/telemetry`)
        setTelemetry(data)
      } catch {}
    }
    void poll()
    const timer = setInterval(() => { void poll() }, 5000)
    return () => clearInterval(timer)
  }, [liveMode, id, activeTab])

  // Sync telemetry data onto edges
  useEffect(() => {
    if (!liveMode) {
      setEdges(eds => eds.map(e => ({ ...e, type: 'custom' })))
      return
    }
    setEdges(eds => eds.map(e => ({
      ...e,
      type: 'telemetry',
      data: { ...e.data, activity: telemetry.activity[e.source] ?? 0, backpressure: telemetry.backpressure[e.source] ?? 0 },
    })))
  }, [telemetry, liveMode, setEdges])

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge({ ...params, type: 'custom' }, eds)), [setEdges])

  const onSaveCanvas = async () => {
    if (!id) return
    try {
      await saveGraph.mutateAsync({
        campaign_id: id,
        nodes: nodes.map(n => {
          // Strip non-serializable React callbacks before persisting
          const { onChange, onEditTemplate, onDelete, ...serializableData } = n.data as any
          return {
            id: n.id,
            node_type: n.type as NodeType,
            position_x: n.position.x,
            position_y: n.position.y,
            data: serializableData,
          }
        }),
        edges: edges.map(e => ({
          source_node_id: e.source,
          target_node_id: e.target,
          source_handle: e.sourceHandle || 'default',
          target_handle: e.targetHandle || 'default'
        }))
      })
      toast.success('Canvas saved.')
    } catch {
      toast.error('Failed to save canvas.')
    }
  }

  const addNode = (type: NodeType) => {
    const newId = `node_${Date.now()}`
    const newNode: Node = {
      id: newId,
      type,
      position: { x: 200 + Math.random() * 50, y: 100 + Math.random() * 50 },
      data: { 
        node_type: type, 
        delay_days: type === 'delay' ? 1 : 0,
        onChange: (id: string, val: number) => updateNodeData(id, { delay_days: val })
      },
    }
    setNodes(nds => nds.concat(newNode))
    setSelectedNodeId(newId)
  }

  const deleteNode = (nodeId: string) => {
    setNodes(nds => nds.filter(n => n.id !== nodeId))
    setEdges(eds => eds.filter(e => e.source !== nodeId && e.target !== nodeId))
    if (selectedNodeId === nodeId) setSelectedNodeId(null)
  }

  // Handle form and data loading
  useEffect(() => {
    if (!campaignQuery.data) return
    setForm({
      name: campaignQuery.data.name,
      daily_lead_cap: campaignQuery.data.daily_lead_cap,
      invite_daily_cap: campaignQuery.data.invite_daily_cap,
      simulation_mode: campaignQuery.data.simulation_mode,
      timezone: campaignQuery.data.timezone,
      active_hours_start: campaignQuery.data.active_hours_start,
      active_hours_end: campaignQuery.data.active_hours_end,
      screening_prompt: campaignQuery.data.screening_prompt || '',
      status: campaignQuery.data.status,
      sequence_mode: campaignQuery.data.sequence_mode,
    })
  }, [campaignQuery.data])

  if (!id) {
    return (
      <div className="space-y-6">
        <section className="flex items-start justify-between rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Campaigns</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Outreach Playbooks</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Build, test, and dispatch multi-channel sequences from a unified dashboard.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="btn-tactile bg-sky-500 px-6 py-3 text-sm text-white hover:bg-sky-600"
          >
            <Plus size={16} className="mr-2" />
            New Campaign
          </button>
        </section>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <DataTable
            columns={[
              { key: 'name', header: 'Campaign', render: (row) => <div><p className="font-medium text-slate-900">{row.name}</p><p className="text-xs uppercase text-slate-400">{row.timezone}</p></div> },
              { key: 'status', header: 'Status', render: (row) => <Badge label={row.status || 'active'} asStatus /> },
              { key: 'daily_lead_cap', header: 'Daily Leads', className: 'text-right', render: (row) => row.daily_lead_cap },
              { key: 'created_at', header: 'Created', render: (row) => formatDate(row.created_at) },
            ]}
            rows={campaignsQuery.data || []}
            loading={campaignsQuery.isLoading}
            onRowClick={(row) => navigate(`/campaigns/${row.id}?tab=leads`)}
          />
        </div>

        <Modal title="New campaign" open={createOpen} onClose={() => setCreateOpen(false)} width="lg">
          <CampaignForm form={form} onChange={setForm} onSubmit={async (e: FormEvent) => { e.preventDefault(); await createCampaign.mutateAsync(form); setCreateOpen(false); }} busy={createCampaign.isPending} submitLabel="Create campaign" />
        </Modal>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-140px)] flex-col gap-6">
      <section className="shrink-0 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-6">
            <Link to="/campaigns" className="text-slate-400 hover:text-slate-600">←</Link>
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{campaignQuery.data?.name || 'Campaign detail'}</h1>
              <div className="flex gap-2 text-xs text-slate-400">
                <Badge label={campaignQuery.data?.status || 'active'} asStatus />
                <span>•</span>
                <span>{campaignQuery.data?.timezone}</span>
                {campaignQuery.data?.simulation_mode && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-amber-600 font-bold">Simulation</span>}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-6">
            {statsQuery.data && (
              <div className="hidden lg:flex items-center divide-x divide-slate-100 rounded-2xl border border-slate-200 bg-slate-50 px-1">
                {[
                  { label: 'Leads', value: statsQuery.data.total },
                  { label: 'Invited', value: statsQuery.data.invited },
                  { label: 'Accepted', value: statsQuery.data.accepted },
                  { label: 'Stopped', value: statsQuery.data.stopped },
                ].map(({ label, value }) => (
                  <div key={label} className="flex flex-col items-center px-4 py-2">
                    <span className="text-lg font-black tabular-nums text-slate-900">{value ?? 0}</span>
                    <span className="text-[9px] font-bold uppercase tracking-widest text-slate-400">{label}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="flex items-center gap-3">
            {activeTab === 'sequence' && campaignQuery.data && (
              <div className="flex rounded-full border border-slate-200 bg-slate-100 p-0.5 text-xs font-semibold">
                {(['sequential', 'canvas'] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => updateCampaign.mutate({ id: id!, payload: { sequence_mode: mode } })}
                    className={`rounded-full px-3 py-1 capitalize transition ${
                      campaignQuery.data.sequence_mode === mode
                        ? 'bg-white text-slate-900 shadow-sm'
                        : 'text-slate-500 hover:text-slate-700'
                    }`}
                  >
                    {mode}
                  </button>
                ))}
              </div>
            )}
            {(['leads', 'queue', 'sequence', 'settings'] as CampaignTab[]).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setSearchParams({ tab })}
                className={`rounded-full px-4 py-1.5 text-xs font-semibold transition ${
                  activeTab === tab ? 'bg-sky-500 text-white' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                }`}
              >
                {tab === 'sequence' ? 'Canvas' : tab.charAt(0).toUpperCase() + tab.slice(1)}
              </button>
            ))}
            </div>
          </div>
        </div>
      </section>

      <div className="flex-1 overflow-hidden relative">
        <div className={`h-full flex gap-6 transition-all duration-300`}>
          <div className="flex-1 overflow-hidden">
            {activeTab === 'leads' && (
              <div className="h-full rounded-3xl border border-slate-200 bg-white p-6 shadow-sm overflow-auto">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-slate-900 uppercase tracking-tight">Leads Pipeline</h2>
                  <button onClick={() => setImportOpen(true)} className="btn-tactile border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50">Import Leads</button>
                </div>
                <DataTable
                  columns={[
                    { key: 'name', header: 'Lead', render: (row) => <div><p className="font-medium text-slate-900">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || 'Unknown'}</p><p className="text-xs text-slate-400">{row.company || '—'}</p></div> },
                    { key: 'status', header: 'Status', render: (row) => <Badge label={row.status || 'active'} asStatus /> },
                    { key: 'invited_at', header: 'Invited', render: (row) => formatDate(row.invited_at) },
                    { key: 'accepted_at', header: 'Accepted', render: (row) => formatDate(row.accepted_at) },
                    { key: 'replied_at', header: 'Replied', render: (row) => formatDate(row.replied_at) },
                  ]}
                  rows={leadsQuery.data?.leads || []}
                  loading={leadsQuery.isLoading}
                />
              </div>
            )}

            {activeTab === 'queue' && (
              <div className="h-full rounded-3xl border border-slate-200 bg-white p-6 shadow-sm overflow-auto">
                <h2 className="text-lg font-semibold text-slate-900 uppercase tracking-tight mb-4">Live Dispatch</h2>
                <DataTable
                  columns={[
                    { key: 'lead', header: 'Lead', render: (row) => row.first_name || row.linkedin_url },
                    { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                    { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
                    { key: 'scheduled_at', header: 'Scheduled', render: (row) => formatDate(row.scheduled_at) },
                  ]}
                  rows={queueQuery.data || []}
                  loading={queueQuery.isLoading}
                />
              </div>
            )}

            {activeTab === 'sequence' && (
              <div className="relative h-full rounded-3xl border border-slate-200 bg-slate-50 shadow-inner">
                {campaignQuery.data?.sequence_mode === 'canvas' ? (
                  <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onConnect={onConnect}
                    onNodeClick={(_, node) => setSelectedNodeId(node.id)}
                    onPaneClick={() => setSelectedNodeId(null)}
                    nodeTypes={nodeTypes}
                    edgeTypes={edgeTypes}
                    defaultEdgeOptions={defaultEdgeOptions}
                    connectionLineType={ConnectionLineType.Bezier}
                    fitView
                    deleteKeyCode="Delete"
                  >
                    <Background color="#cbd5e1" gap={24} />
                    <Controls />
                    <NodePalette onAdd={addNode} />
                    <Panel position="top-right">
                      <div className="flex gap-2">
                        <button
                          onClick={() => setLiveMode(m => !m)}
                          className={`btn-tactile flex items-center px-4 py-3 text-xs font-bold shadow-xl transition ${liveMode ? 'bg-emerald-500 text-white shadow-emerald-200 hover:bg-emerald-600' : 'bg-white text-slate-600 shadow-slate-200 hover:bg-slate-50'}`}
                        >
                          <Radio size={13} className={`mr-1.5 ${liveMode ? 'animate-pulse' : ''}`} />
                          Live
                        </button>
                        <button
                          onClick={onSaveCanvas}
                          disabled={saveGraph.isPending}
                          className="btn-tactile flex items-center bg-slate-900 px-6 py-3 text-xs font-bold text-white shadow-xl shadow-slate-200 transition hover:bg-slate-800"
                        >
                          <Save size={16} className="mr-2" />
                          {saveGraph.isPending ? 'Syncing...' : 'Deploy Canvas'}
                        </button>
                      </div>
                    </Panel>
                  </ReactFlow>
                ) : (
                  <SequentialBuilder
                    nodes={nodes}
                    edges={edges}
                    onSave={(newNodes, newEdges) => {
                      setNodes(newNodes)
                      setEdges(newEdges)
                      saveGraph.mutate({
                        campaign_id: id!,
                        nodes: newNodes.map(n => { const { onChange, onEditTemplate, onDelete, ...d } = n.data as any; return { id: n.id, node_type: n.type as NodeType, position_x: n.position.x, position_y: n.position.y, data: d } }),
                        edges: newEdges.map(e => ({ source_node_id: e.source, target_node_id: e.target, source_handle: e.sourceHandle || 'default', target_handle: e.targetHandle || 'default' }))
                      })
                    }}
                    onEditTemplate={setSelectedNodeId}
                    isSaving={saveGraph.isPending}
                  />
                )}
              </div>
            )}

            {activeTab === 'settings' && (
              <div className="h-full overflow-auto rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
                <CampaignSettings campaignId={id!} />
              </div>
            )}
          </div>

          {activeTab === 'sequence' && campaignQuery.data?.sequence_mode === 'canvas' && (
            <div className={`w-80 bg-white border-l border-slate-200 transition-all ${selectedNodeId ? 'mr-0' : '-mr-80'}`}>
              <ConfigSidebar 
                nodeId={selectedNodeId} 
                nodes={nodes} 
                onClose={() => setSelectedNodeId(null)}
                onUpdate={(data) => updateNodeData(selectedNodeId!, data)}
                onDelete={() => deleteNode(selectedNodeId!)}
              />
            </div>
          )}
        </div>
      </div>

      <Modal title="Import leads" open={importOpen} onClose={() => setImportOpen(false)} width="lg">
        <form className="space-y-4" onSubmit={async (e: FormEvent) => {
          e.preventDefault()
          const parsed = JSON.parse(importPayload)
          await importLeads.mutateAsync({ campaignId: id!, leads: parsed })
          setImportOpen(false)
          setImportPayload('')
          toast.success('Leads imported.')
        }}>
          <textarea
            value={importPayload}
            onChange={(e) => setImportPayload(e.target.value)}
            className="min-h-[260px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm"
            placeholder='[{"linkedin_url":"..."}]'
          />
          <button type="submit" className="w-full rounded-xl bg-sky-500 py-3 font-semibold text-white">Import Leads</button>
        </form>
      </Modal>
    </div>
  )
}

function NodePalette({ onAdd }: { onAdd: (type: NodeType) => void }) {
  return (
    <div className="absolute left-4 top-4 z-10 flex w-48 flex-col gap-1 rounded-2xl border border-slate-200 bg-white p-2 shadow-xl">
      <p className="px-3 pb-2 pt-1 text-[10px] font-black uppercase tracking-[0.2em] text-slate-400">Add Module</p>
      <button
        onClick={() => onAdd('trigger_start')}
        className="flex items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-xs font-bold text-white transition hover:bg-slate-800"
      >
        <Zap size={14} fill="currentColor" /> Genesis Trigger
      </button>
      <div className="my-2 h-px bg-slate-100" />
      <div className="space-y-1">
        {NODE_PALETTE.map(({ type, label, icon, color, bg, border }) => (
          <button
            key={type}
            onClick={() => onAdd(type)}
            className={`flex w-full items-center gap-3 rounded-xl border border-transparent px-4 py-2.5 text-xs font-bold transition hover:border-slate-200 hover:bg-slate-50 ${color}`}
          >
            {icon} {label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ConfigSidebar({ nodeId, nodes, onClose, onUpdate, onDelete }: { 
  nodeId: string | null; 
  nodes: Node[]; 
  onClose: () => void;
  onUpdate: (data: any) => void;
  onDelete: () => void;
}) {
  const node = nodes.find(n => n.id === nodeId)
  const nodeType = node?.type as NodeType
  const toast = useToast()
  const { id: campaignId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const templateQuery = useGetTemplate(nodeId || undefined)
  const upsertTemplate = useUpsertTemplate()

  const emailAccountsQuery = useQuery({
    queryKey: ['accounts', 'email'],
    queryFn: async () => (await api.get<EmailAccount[]>('/accounts/email')).data,
  })
  const voiceAgentsQuery = useQuery({
    queryKey: ['accounts', 'voice'],
    queryFn: async () => (await api.get<VoiceAgent[]>('/accounts/voice')).data,
  })

  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')

  const [agentPrompt, setAgentPrompt] = useState<RetellPrompt | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [flowMeta, setFlowMeta] = useState<{ node_count: number; edge_count: number } | null>(null);

  const selectedVoiceAgentId = (node?.data as any)?.voice_agent_id;
  const mode = (node?.data as any)?.mode || 'standard';

  useEffect(() => {
    setAgentPrompt(null);
    setPromptError(null);
    setPromptSaving(false);
    setFlowMeta(null);
    if (mode !== 'standard' || !selectedVoiceAgentId) return;
    setPromptLoading(true);
    api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
      .then(r => { setAgentPrompt(r.data); setPromptError(null); })
      .catch((err) => {
        const status = err?.response?.status;
        if (status === 400) {
          setPromptError('This agent uses Nested Flow and cannot be edited in Standard mode. Switch to Nested Flow mode above.');
        } else {
          toast.error('Failed to load agent prompt');
        }
      })
      .finally(() => setPromptLoading(false));
  }, [selectedVoiceAgentId, mode]);

  useEffect(() => {
    if (mode !== 'flow' || !selectedVoiceAgentId) return;
    api.get(`/accounts/voice/${selectedVoiceAgentId}/flow`)
      .then(r => {
        const flowNodes = r.data.nodes ?? [];
        const flowEdges = flowNodes.flatMap((n: any) => [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])]);
        setFlowMeta({ node_count: flowNodes.length, edge_count: flowEdges.length });
      })
      .catch(() => setFlowMeta(null));
  }, [selectedVoiceAgentId, mode, location.key]);
  useEffect(() => {
    if (templateQuery.data) {
      setSubject(templateQuery.data.subject ?? '')
      setBody(templateQuery.data.body ?? '')
    } else {
      setSubject('')
      setBody('')
    }
  }, [templateQuery.data])

  if (!node) return null

  const isEmail = nodeType === 'action_email'
  const isVoice = nodeType === 'action_voice'
  const isDelay = nodeType === 'delay'
  const isTagNode = nodeType === 'action_add_tag' || nodeType === 'action_remove_tag' || nodeType === 'condition_tag_exists'
  const needsTemplate = nodeType.startsWith('action_') && nodeType !== 'action_linkedin_invite' && nodeType !== 'action_voice' && !isTagNode

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between p-6 border-b border-slate-100">
        <h3 className="text-sm font-black uppercase tracking-widest text-slate-900">Module Config</h3>
        <button onClick={onClose} className="p-2 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-900 transition-all"><X size={18} /></button>
      </div>

      <div className="flex-1 overflow-auto p-6 space-y-8">
        {isVoice && (
          <div>
            <label className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3 block">Operation Mode</label>
            <div className="grid grid-cols-2 gap-2 p-1 bg-slate-50 rounded-xl ring-1 ring-slate-900/5">
              <button 
                onClick={() => onUpdate({ mode: 'standard' })}
                className={`py-2 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${((node.data as any).mode || 'standard') === 'standard' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}
              >
                Standard
              </button>
              <button 
                onClick={() => onUpdate({ mode: 'flow' })}
                className={`py-2 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${((node.data as any).mode || 'standard') === 'flow' ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}
              >
                Nested Flow
              </button>
            </div>
          </div>
        )}

        <div>
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2 block">Module Type</label>
          <div className="flex items-center gap-3 bg-slate-50 p-4 rounded-2xl ring-1 ring-slate-900/5">
            <StepIcon type={nodeType} />
            <span className="text-sm font-bold text-slate-900 capitalize">{nodeType.replace('action_', '').replace('_', ' ')}</span>
          </div>
        </div>

        {isDelay && (
          <div>
            <label className={labelCls}>Wait Duration (Days)</label>
            <input 
              type="number" 
              min="1" 
              value={(node.data as any).delay_days || 1} 
              onChange={(e) => onUpdate({ delay_days: parseInt(e.target.value) || 1 })}
              className={inputClassName}
            />
          </div>
        )}

        {isTagNode && (
          <div>
            <label className={labelCls}>Tag Name</label>
            <input 
              type="text" 
              value={(node.data as any).tag || ''} 
              onChange={(e) => onUpdate({ tag: e.target.value })}
              className={inputClassName}
              placeholder="e.g., high-priority"
            />
          </div>
        )}

        {isEmail && (
          <div>
            <label className={labelCls}>Sending Account</label>
            <select 
              value={(node.data as any).email_account_id || ''} 
              onChange={(e) => onUpdate({ email_account_id: e.target.value })}
              className={inputClassName}
            >
              <option value="">Select identity...</option>
              {(emailAccountsQuery.data || []).map(a => <option key={a.id} value={a.id}>{a.from_name}</option>)}
            </select>
          </div>
        )}

        {isVoice && (
          <div className="space-y-4">
            <div>
              <label className={labelCls}>Voice Agent</label>
              <select 
                value={(node.data as any).voice_agent_id || ''} 
                onChange={(e) => onUpdate({ voice_agent_id: e.target.value })}
                className={inputClassName}
              >
                <option value="">Select agent...</option>
                {(voiceAgentsQuery.data || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            
            {mode === 'standard' && selectedVoiceAgentId && (
              <div className="space-y-4 mt-6">
                {promptLoading ? (
                  <div className="space-y-3 animate-pulse">
                    <div className="h-4 bg-slate-100 rounded w-1/4" />
                    <div className="h-10 bg-slate-50 rounded" />
                    <div className="h-4 bg-slate-100 rounded w-1/4" />
                    <div className="h-32 bg-slate-50 rounded" />
                  </div>
                ) : promptError ? (
                  <div className="rounded-xl bg-rose-950/40 border border-rose-800/50 p-4">
                    <p className="text-[11px] text-rose-300 leading-relaxed">{promptError}</p>
                  </div>
                ) : agentPrompt ? (
                  <>
                    <div>
                      <label className={labelCls}>Begin Message</label>
                      <input
                        className={inputClassName}
                        value={agentPrompt.begin_message}
                        onChange={e => setAgentPrompt(p => p ? { ...p, begin_message: e.target.value } : p)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>System Prompt</label>
                      <textarea
                        className={`${inputClassName} min-h-[200px] resize-none`}
                        value={agentPrompt.general_prompt}
                        onChange={e => setAgentPrompt(p => p ? { ...p, general_prompt: e.target.value } : p)}
                      />
                    </div>
                    <button
                      disabled={promptSaving}
                      onClick={async () => {
                        if (!agentPrompt) return;
                        setPromptSaving(true);
                        try {
                          await api.patch(`/accounts/voice/${selectedVoiceAgentId}/prompt`, {
                            begin_message: agentPrompt.begin_message,
                            general_prompt: agentPrompt.general_prompt,
                          });
                          toast.success('Prompt saved');
                        } catch {
                          toast.error('Failed to save prompt');
                        } finally {
                          setPromptSaving(false);
                        }
                      }}
                      className="w-full btn-tactile bg-slate-900 py-3 text-[10px] font-black uppercase tracking-widest text-white hover:bg-slate-800 disabled:opacity-40"
                    >
                      {promptSaving ? 'Saving...' : 'Save Prompt'}
                    </button>
                  </>
                ) : null}
              </div>
            )}

            {mode === 'flow' && selectedVoiceAgentId && (
              <div className="mt-6 space-y-4">
                <button
                  onClick={() => navigate(`/campaigns/${campaignId}/voice-flow/${selectedVoiceAgentId}`)}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-xl bg-sky-500 text-white text-[10px] font-black uppercase tracking-widest hover:bg-sky-600 transition-all"
                >
                  <span>Open Flow Editor</span>
                  <span className="text-sky-100">→</span>
                </button>
                {flowMeta && (
                  <p className="text-[10px] font-bold text-slate-400 text-center uppercase tracking-widest">
                    {flowMeta.node_count} nodes · {flowMeta.edge_count} edges
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {needsTemplate && (
          <div className="space-y-4 pt-4 border-t border-slate-100">
            {isEmail && (
              <div>
                <label className={labelCls}>Subject Line</label>
                <input value={subject} onChange={(e) => setSubject(e.target.value)} className={inputClassName} />
              </div>
            )}
            <div>
              <label className={labelCls}>Message / Script</label>
              <textarea 
                value={body} 
                onChange={(e) => setBody(e.target.value)} 
                className={`${inputClassName} min-h-[200px] resize-none text-pretty`}
                placeholder="Hi {{first_name}}, ..."
              />
            </div>
            <button 
              onClick={async () => {
                await upsertTemplate.mutateAsync({ node_id: nodeId!, subject: subject || null, body })
                toast.success('Script updated.')
              }}
              disabled={upsertTemplate.isPending}
              className="w-full btn-tactile bg-slate-100 py-3 text-[10px] font-black uppercase tracking-widest text-slate-600 hover:bg-slate-200"
            >
              {upsertTemplate.isPending ? 'Syncing...' : 'Update Script'}
            </button>
          </div>
        )}
      </div>

      <div className="p-6 border-t border-slate-100">
        <button 
          onClick={onDelete}
          className="w-full flex items-center justify-center gap-2 py-3 text-[10px] font-black uppercase tracking-widest text-rose-500 hover:bg-rose-50 rounded-xl transition-all"
        >
          <Trash2 size={14} /> Remove Module
        </button>
      </div>
    </div>
  )
}

function StepIcon({ type }: { type: NodeType }) {
  const common = { size: 18, strokeWidth: 2, className: "text-slate-600" }
  switch (type) {
    case 'action_linkedin_invite':
    case 'action_linkedin_dm': return <Linkedin {...common} className="text-sky-500" />
    case 'action_email': return <Mail {...common} className="text-slate-500" />
    case 'action_whatsapp': return <MessageSquare {...common} className="text-emerald-500" />
    case 'action_instagram': return <Instagram {...common} className="text-pink-500" />
    case 'action_telegram': return <Send {...common} className="text-blue-500" />
    case 'action_voice': return <Phone {...common} className="text-indigo-500" />
    case 'delay': return <Clock {...common} className="text-amber-500" />
    default: return <Zap {...common} />
  }
}

// ── Shared UI Parts ────────────────────────────────────────────────────────

function CampaignSettings({ campaignId }: { campaignId: string }) {
  const toast = useToast()
  const campaignQuery = useGetCampaign(campaignId)
  const updateCampaign = useUpdateCampaign()
  const queryClient = useQueryClient()

  const [form, setForm] = useState<Partial<CampaignPayload>>({})
  const [dirty, setDirty] = useState(false)

  const linkedinAccountsQuery = useQuery({
    queryKey: ['settings', 'linkedin'],
    queryFn: async () => (await api.get<LinkedInAccount[]>('/accounts/linkedin')).data,
  })
  const assignedQuery = useQuery({
    queryKey: ['campaign-accounts', campaignId],
    queryFn: async () => (await api.get<LinkedInAccount[]>(`/campaigns/${campaignId}/accounts`)).data,
  })

  useEffect(() => {
    if (campaignQuery.data && !dirty) {
      const c = campaignQuery.data
      setForm({
        name: c.name,
        timezone: c.timezone,
        daily_lead_cap: c.daily_lead_cap,
        invite_daily_cap: c.invite_daily_cap,
        active_hours_start: c.active_hours_start,
        active_hours_end: c.active_hours_end,
        simulation_mode: c.simulation_mode,
        screening_prompt: c.screening_prompt ?? '',
        sequence_mode: c.sequence_mode,
      })
    }
  }, [campaignQuery.data, dirty])

  const assignedIds = new Set((assignedQuery.data ?? []).map(a => a.id))

  const toggleAccount = async (accountId: string) => {
    if (assignedIds.has(accountId)) {
      await api.delete(`/campaigns/${campaignId}/accounts/${accountId}`)
    } else {
      await api.post(`/campaigns/${campaignId}/accounts`, { account_id: accountId })
    }
    void queryClient.invalidateQueries({ queryKey: ['campaign-accounts', campaignId] })
  }

  if (campaignQuery.isLoading) return <p className="text-sm text-slate-400">Loading…</p>

  return (
    <div className="space-y-10 max-w-2xl">
      <form onSubmit={async (e) => { e.preventDefault(); await updateCampaign.mutateAsync({ id: campaignId, payload: form }); setDirty(false); toast.success('Saved.'); }} className="space-y-6">
        <h2 className="text-sm font-black uppercase tracking-widest text-slate-900">Campaign Configuration</h2>
        <div className="grid grid-cols-2 gap-4">
          <label className="block"><span className={labelCls}>Name</span><input value={form.name ?? ''} onChange={e => { setForm({ ...form, name: e.target.value }); setDirty(true); }} className={inputClassName} required /></label>
          <label className="block"><span className={labelCls}>Timezone</span><input value={form.timezone ?? ''} onChange={e => { setForm({ ...form, timezone: e.target.value }); setDirty(true); }} className={inputClassName} required /></label>
          <label className="block"><span className={labelCls}>Daily Lead Cap</span><input type="number" min="1" value={form.daily_lead_cap ?? 50} onChange={e => { setForm({ ...form, daily_lead_cap: parseInt(e.target.value) || 1 }); setDirty(true); }} className={inputClassName} /></label>
          <label className="block"><span className={labelCls}>Daily Invite Cap</span><input type="number" min="1" value={form.invite_daily_cap ?? 20} onChange={e => { setForm({ ...form, invite_daily_cap: parseInt(e.target.value) || 1 }); setDirty(true); }} className={inputClassName} /></label>
          <label className="block"><span className={labelCls}>Active Hours Start (0–23)</span><input type="number" min="0" max="23" value={form.active_hours_start ?? 9} onChange={e => { setForm({ ...form, active_hours_start: parseInt(e.target.value) }); setDirty(true); }} className={inputClassName} /></label>
          <label className="block"><span className={labelCls}>Active Hours End (0–23)</span><input type="number" min="0" max="23" value={form.active_hours_end ?? 18} onChange={e => { setForm({ ...form, active_hours_end: parseInt(e.target.value) }); setDirty(true); }} className={inputClassName} /></label>
        </div>
        <label className="block"><span className={labelCls}>Screening Prompt</span><textarea value={form.screening_prompt ?? ''} onChange={e => { setForm({ ...form, screening_prompt: e.target.value }); setDirty(true); }} className={`${inputClassName} min-h-[120px] resize-none`} placeholder="Describe what makes a good lead for this campaign…" /></label>
        <label className="flex items-center gap-3 cursor-pointer select-none">
          <div onClick={() => { setForm({ ...form, simulation_mode: !form.simulation_mode }); setDirty(true); }} className={`relative h-6 w-11 rounded-full transition-colors ${form.simulation_mode ? 'bg-amber-400' : 'bg-slate-200'}`}>
            <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${form.simulation_mode ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </div>
          <span className={labelCls + ' mb-0'}>Simulation Mode {form.simulation_mode ? <span className="text-amber-500">(dry-run — no real sends)</span> : ''}</span>
        </label>
        <button type="submit" disabled={!dirty} className="btn-tactile bg-sky-500 px-6 py-2.5 text-xs text-white disabled:opacity-40">Save Changes</button>
      </form>

      <div className="pt-8 border-t border-slate-100">
        <h2 className="text-sm font-black uppercase tracking-widest text-slate-900 mb-4">Assigned Sending Nodes</h2>
        <div className="space-y-2">
          {(linkedinAccountsQuery.data || []).map(acct => (
            <div key={acct.id} className="flex items-center justify-between p-4 rounded-2xl bg-slate-50 ring-1 ring-slate-900/5">
              <span className="text-sm font-bold text-slate-900">{acct.name}</span>
              <button onClick={() => toggleAccount(acct.id)} className={`px-4 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest ${assignedIds.has(acct.id) ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-200 text-slate-500'}`}>
                {assignedIds.has(acct.id) ? 'Active' : 'Enable'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function CampaignForm({ form, onChange, onSubmit, busy, submitLabel }: any) {
  const update = (key: string, val: any) => onChange({ ...form, [key]: val })
  return (
    <form className="space-y-6" onSubmit={onSubmit}>
      <input value={form.name} onChange={(e) => update('name', e.target.value)} placeholder="Campaign Name" className={inputClassName} required />
      <div className="grid grid-cols-2 gap-4">
        <button type="button" onClick={() => update('sequence_mode', 'sequential')} className={`btn-tactile p-6 border-2 flex flex-col gap-2 ${form.sequence_mode === 'sequential' ? 'border-sky-500 bg-sky-50' : 'border-slate-100 bg-slate-50'}`}>
          <Clock size={20} className={form.sequence_mode === 'sequential' ? 'text-sky-500' : 'text-slate-400'} />
          <span className="text-xs font-black uppercase">Sequential</span>
        </button>
        <button type="button" onClick={() => update('sequence_mode', 'canvas')} className={`btn-tactile p-6 border-2 flex flex-col gap-2 ${form.sequence_mode === 'canvas' ? 'border-sky-500 bg-sky-50' : 'border-slate-100 bg-slate-50'}`}>
          <Zap size={20} className={form.sequence_mode === 'canvas' ? 'text-sky-500' : 'text-slate-400'} />
          <span className="text-xs font-black uppercase">Canvas</span>
        </button>
      </div>
      <button type="submit" disabled={busy} className="btn-tactile w-full bg-sky-500 py-4 text-xs text-white">{busy ? 'Creating...' : submitLabel}</button>
    </form>
  )
}

const labelCls = 'mb-2 block text-[10px] font-black uppercase tracking-widest text-slate-400'
const inputClassName = 'w-full rounded-xl border-none bg-slate-50 px-4 py-3 text-sm font-bold text-slate-900 outline-none ring-1 ring-slate-900/5 transition-all focus:bg-white focus:ring-4 focus:ring-sky-100'

type EmailAccount = { id: string; from_name: string; from_email: string }
type VoiceAgent = { id: string; name: string; retell_agent_id: string }
type LinkedInAccount = { id: string; name: string; unipile_id: string; is_active: boolean }
