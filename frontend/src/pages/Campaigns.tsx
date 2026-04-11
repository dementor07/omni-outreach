import { FormEvent, useEffect, useState, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Plus, Save, Mail, Linkedin, Phone, MessageSquare, Instagram, Send, Clock, Zap } from 'lucide-react'
import { 
  ReactFlow, 
  Background, 
  Controls, 
  useNodesState, 
  useEdgesState, 
  addEdge, 
  Connection, 
  Edge,
  Node,
  Handle,
  Position,
  NodeProps,
  Panel
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

// ── Node palette config ────────────────────────────────────────────────────

const NODE_PALETTE: { type: NodeType; label: string; icon: React.ReactNode; color: string; bg: string; border: string }[] = [
  { type: 'action_linkedin_invite', label: 'LinkedIn Invite', icon: <Linkedin size={15} />, color: 'text-sky-600',     bg: 'bg-sky-50',     border: 'border-sky-200' },
  { type: 'action_linkedin_dm',     label: 'LinkedIn DM',     icon: <Linkedin size={15} />, color: 'text-sky-500',     bg: 'bg-sky-50',     border: 'border-sky-200' },
  { type: 'action_email',           label: 'Email',           icon: <Mail size={15} />,     color: 'text-slate-600',   bg: 'bg-slate-50',   border: 'border-slate-200' },
  { type: 'action_whatsapp',        label: 'WhatsApp',        icon: <MessageSquare size={15} />, color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  { type: 'action_instagram',       label: 'Instagram',       icon: <Instagram size={15} />, color: 'text-pink-500',   bg: 'bg-pink-50',    border: 'border-pink-200' },
  { type: 'action_telegram',        label: 'Telegram',        icon: <Send size={15} />,     color: 'text-blue-500',    bg: 'bg-blue-50',    border: 'border-blue-200' },
  { type: 'action_voice',           label: 'Voice Call',      icon: <Phone size={15} />,    color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200' },
  { type: 'condition_replied',      label: 'Branch: Reply?',  icon: <Zap size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'delay',                  label: 'Wait / Delay',    icon: <Clock size={15} />,    color: 'text-slate-400',   bg: 'bg-slate-50',   border: 'border-slate-200' },
]

// ── React Flow Node Types ──────────────────────────────────────────────────

interface ActionNodeData extends Record<string, unknown> {
  node_type: NodeType
  email_account_id?: string
  voice_agent_id?: string
  delay_days?: number
  onEditTemplate: (id: string) => void
  onDelete: (id: string) => void
}

const ActionNode = ({ data, id }: NodeProps<Node<ActionNodeData>>) => {
  const nodeType = data.node_type
  const cfg = NODE_PALETTE.find(p => p.type === nodeType)
  const configured = !!(data.email_account_id || data.voice_agent_id || nodeType === 'action_linkedin_invite')
  return (
    <div className={`nodrag-ignore group relative w-56 rounded-2xl border-2 bg-white shadow-sm transition-all hover:shadow-md ${cfg?.border ?? 'border-slate-200'}`}>
      <Handle type="target" position={Position.Top} className="!h-3 !w-3 !border-2 !border-white !bg-slate-400" />
      {/* Header */}
      <div className={`flex items-center justify-between rounded-t-xl px-3 py-2 ${cfg?.bg ?? 'bg-slate-50'}`}>
        <div className="flex items-center gap-2">
          <span className={cfg?.color ?? 'text-slate-500'}>{cfg?.icon}</span>
          <span className={`text-xs font-bold uppercase tracking-wide ${cfg?.color ?? 'text-slate-500'}`}>{cfg?.label ?? nodeType}</span>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); data.onDelete(id) }}
          className="rounded-lg p-0.5 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-400 group-hover:opacity-100"
          title="Delete node"
        >✕</button>
      </div>
      {/* Status */}
      <div className="px-3 py-2">
        <span className={`text-[11px] ${configured ? 'text-emerald-500 font-medium' : 'italic text-slate-300'}`}>
          {configured ? '✓ Configured' : 'Not configured'}
        </span>
      </div>
      {/* Configure button */}
      <button
        onClick={() => data.onEditTemplate(id)}
        className="w-full rounded-b-xl border-t border-slate-100 py-1.5 text-[11px] font-semibold text-slate-500 transition hover:bg-sky-50 hover:text-sky-600"
      >
        Configure →
      </button>
      <Handle type="source" position={Position.Bottom} className="!h-3 !w-3 !border-2 !border-white !bg-slate-400" />
    </div>
  )
}

const TriggerNode = ({ id, data }: NodeProps<Node<ActionNodeData>>) => (
  <div className="group relative w-48 rounded-2xl border-2 border-emerald-400 bg-emerald-50 p-4 text-center shadow-md">
    <button
      onClick={(e) => { e.stopPropagation(); data.onDelete?.(id) }}
      className="absolute right-2 top-2 rounded-lg p-0.5 text-emerald-300 opacity-0 transition hover:bg-emerald-100 hover:text-rose-400 group-hover:opacity-100"
      title="Delete node"
    >✕</button>
    <div className="mx-auto mb-2 flex h-8 w-8 items-center justify-center rounded-full bg-emerald-400">
      <Zap size={14} className="text-white" />
    </div>
    <p className="text-[10px] font-bold uppercase tracking-wider text-emerald-600">Start</p>
    <p className="text-sm font-semibold text-emerald-900">Lead Accepted</p>
    <Handle type="source" position={Position.Bottom} className="!h-3 !w-3 !border-2 !border-white !bg-emerald-500" />
  </div>
)

const ConditionNode = ({ id, data }: NodeProps<Node<ActionNodeData>>) => (
  <div className="group relative w-56 rounded-2xl border-2 border-amber-300 bg-white shadow-sm transition-all hover:shadow-md">
    <Handle type="target" position={Position.Top} className="!h-3 !w-3 !border-2 !border-white !bg-slate-400" />
    <div className="flex items-center justify-between rounded-t-xl bg-amber-50 px-3 py-2">
      <div className="flex items-center gap-2">
        <Zap size={15} className="text-amber-500" />
        <span className="text-xs font-bold uppercase tracking-wide text-amber-600">Branch: Reply?</span>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); data.onDelete?.(id) }}
        className="rounded-lg p-0.5 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-400 group-hover:opacity-100"
        title="Delete node"
      >✕</button>
    </div>
    <div className="grid grid-cols-2 divide-x divide-slate-100 border-t border-slate-100 px-2 py-3">
      <div className="flex flex-col items-center gap-2">
        <span className="text-[10px] font-semibold text-emerald-600">Replied ✓</span>
        <Handle type="source" id="true" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!h-3 !w-3 !border-2 !border-white !bg-emerald-400" />
      </div>
      <div className="flex flex-col items-center gap-2">
        <span className="text-[10px] font-semibold text-rose-500">No Reply ✗</span>
        <Handle type="source" id="false" position={Position.Bottom} style={{ position: 'relative', top: 'auto', left: 'auto', transform: 'none' }} className="!h-3 !w-3 !border-2 !border-white !bg-rose-400" />
      </div>
    </div>
  </div>
)

const DelayNode = ({ id, data }: NodeProps<Node<ActionNodeData>>) => (
  <div className="group relative w-44 rounded-2xl border-2 border-slate-200 bg-white px-4 py-3 shadow-sm transition-all hover:border-slate-300 hover:shadow-md">
    <Handle type="target" position={Position.Top} className="!h-3 !w-3 !border-2 !border-white !bg-slate-400" />
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Clock size={14} className="text-slate-400" />
        <span className="text-sm font-semibold text-slate-600">Wait {(data.delay_days as number) ?? 1}d</span>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); data.onDelete?.(id) }}
        className="rounded-lg p-0.5 text-slate-300 opacity-0 transition hover:bg-rose-50 hover:text-rose-400 group-hover:opacity-100"
        title="Delete node"
      >✕</button>
    </div>
    <Handle type="source" position={Position.Bottom} className="!h-3 !w-3 !border-2 !border-white !bg-slate-400" />
  </div>
)

const nodeTypes = {
  trigger_start: TriggerNode,
  action_linkedin_invite: ActionNode,
  action_linkedin_dm: ActionNode,
  action_email: ActionNode,
  action_whatsapp: ActionNode,
  action_instagram: ActionNode,
  action_telegram: ActionNode,
  action_voice: ActionNode,
  condition_replied: ConditionNode,
  delay: DelayNode,
}

// ── Left palette sidebar ───────────────────────────────────────────────────

function NodePalette({ onAdd }: { onAdd: (type: NodeType) => void }) {
  return (
    <div className="absolute left-3 top-3 z-10 flex w-44 flex-col gap-1 rounded-2xl border border-slate-200 bg-white p-2 shadow-lg">
      <p className="px-2 pb-1 text-[10px] font-bold uppercase tracking-widest text-slate-400">Add node</p>
      <button
        onClick={() => onAdd('trigger_start')}
        className="flex items-center gap-2 rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-700 hover:bg-emerald-100 transition"
      >
        <Zap size={14} /> Start Trigger
      </button>
      <div className="my-1 h-px bg-slate-100" />
      {NODE_PALETTE.map(({ type, label, icon, color, bg }) => (
        <button
          key={type}
          onClick={() => onAdd(type)}
          className={`flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold transition hover:opacity-80 ${bg} ${color}`}
        >
          {icon} {label}
        </button>
      ))}
    </div>
  )
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
  const [configNodeId, setConfigNodeId] = useState<string | null>(null)
  
  const [createOpen, setCreateOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [form, setForm] = useState<CampaignPayload>(defaultCampaignForm)
  const [importPayload, setImportPayload] = useState('')

  const deleteNode = useCallback((nodeId: string) => {
    setNodes(nds => nds.filter(n => n.id !== nodeId))
    setEdges(eds => eds.filter(e => e.source !== nodeId && e.target !== nodeId))
  }, [setNodes, setEdges])

  const makeNodeData = useCallback((base: Record<string, unknown>, nodeType: string) => ({
    ...base,
    node_type: nodeType,
    onEditTemplate: (nid: string) => setConfigNodeId(nid),
    onDelete: (nid: string) => deleteNode(nid),
  }), [deleteNode])

  // Sync React Flow state with database
  useEffect(() => {
    if (graphQuery.data) {
      const rfNodes: Node[] = graphQuery.data.nodes.map(n => ({
        id: n.id,
        type: n.node_type,
        position: { x: n.position_x, y: n.position_y },
        data: makeNodeData(n.data as Record<string, unknown>, n.node_type),
      }))
      const rfEdges: Edge[] = graphQuery.data.edges.map(e => ({
        id: e.id,
        source: e.source_node_id,
        target: e.target_node_id,
        sourceHandle: e.source_handle,
        targetHandle: e.target_handle,
      }))
      setNodes(rfNodes)
      setEdges(rfEdges)
    }
  }, [graphQuery.data, setNodes, setEdges, makeNodeData])

  const onConnect = useCallback((params: Connection) => setEdges((eds) => addEdge(params, eds)), [setEdges])

  const onSaveCanvas = async () => {
    if (!id) return
    try {
      await saveGraph.mutateAsync({
        campaign_id: id,
        nodes: nodes.map(n => ({
          id: n.id,
          node_type: n.type as NodeType,
          position_x: n.position.x,
          position_y: n.position.y,
          data: n.data
        })),
        edges: edges.map(e => ({
          source_node_id: e.source,
          target_node_id: e.target,
          source_handle: e.sourceHandle || 'default',
          target_handle: e.targetHandle || 'default'
        }))
      })
      toast.success('Canvas saved successfully.')
    } catch {
      toast.error('Failed to save canvas.')
    }
  }

  const addNode = (type: NodeType) => {
    const newId = `node_${Date.now()}`
    const newNode: Node = {
      id: newId,
      type,
      position: { x: 200 + Math.random() * 100, y: 100 + Math.random() * 100 },
      data: makeNodeData({ delay_days: type === 'delay' ? 1 : undefined }, type),
    }
    setNodes(nds => nds.concat(newNode))
  }

  const clearCanvas = async () => {
    if (!id) return
    setNodes([])
    setEdges([])
    await saveGraph.mutateAsync({ campaign_id: id, nodes: [], edges: [] })
    toast.success('Canvas cleared.')
  }

  // ... (Keep existing useEffect for form and handleCreate/Save/Archive/Import)
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

  const campaignRows = campaignsQuery.data || []
  const detailLeads = leadsQuery.data?.leads || []
  const detailQueue = queueQuery.data || []
  const stats = statsQuery.data

  if (!id) {
    return (
      <div className="space-y-6">
        <section className="flex items-start justify-between rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Campaigns</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Configure the outreach engine campaign by campaign</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Build campaign constraints, choose operating hours, and drop into deeper views when you need leads or queue detail.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-sky-600"
          >
            <Plus size={16} />
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
            rows={campaignRows}
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
                <span>{campaignQuery.data?.status}</span>
                <span>•</span>
                <span>{campaignQuery.data?.timezone}</span>
              </div>
            </div>
          </div>
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
      </section>

      <div className="flex-1 overflow-hidden">
        {activeTab === 'leads' && (
          <div className="h-full rounded-3xl border border-slate-200 bg-white p-6 shadow-sm overflow-auto">
             <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-slate-900">Leads</h2>
              <button onClick={() => setImportOpen(true)} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium hover:bg-slate-50">Import Leads</button>
            </div>
            <DataTable
              columns={[
                { key: 'name', header: 'Lead', render: (row) => `${row.first_name || ''} ${row.last_name || ''}` },
                { key: 'status', header: 'Status', render: (row) => <Badge label={row.status || 'active'} asStatus /> },
                { key: 'replied_at', header: 'Replied', render: (row) => formatDate(row.replied_at) },
              ]}
              rows={detailLeads}
              loading={leadsQuery.isLoading}
            />
          </div>
        )}

        {activeTab === 'queue' && (
          <div className="h-full rounded-3xl border border-slate-200 bg-white p-6 shadow-sm overflow-auto">
            <h2 className="text-lg font-semibold text-slate-900">Queue</h2>
            <DataTable
              columns={[
                { key: 'lead', header: 'Lead', render: (row) => row.first_name || row.linkedin_url },
                { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
                { key: 'scheduled_at', header: 'Scheduled', render: (row) => formatDate(row.scheduled_at) },
              ]}
              rows={detailQueue}
              loading={queueQuery.isLoading}
            />
          </div>
        )}
...
        {activeTab === 'sequence' && (
          <div className="relative h-full rounded-3xl border border-slate-200 bg-slate-50 shadow-inner">
            {campaignQuery.data?.sequence_mode === 'canvas' ? (
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                nodeTypes={nodeTypes}
                fitView
                deleteKeyCode="Delete"
              >
                <Background color="#e2e8f0" gap={24} />
                <Controls />
                <NodePalette onAdd={addNode} />
                <Panel position="top-right">
                  <div className="flex gap-2">
                    <button
                      onClick={() => { if (window.confirm('Clear all nodes and edges?')) clearCanvas() }}
                      className="inline-flex items-center gap-2 rounded-2xl border border-rose-200 bg-white px-4 py-2.5 text-sm font-semibold text-rose-500 shadow-sm transition hover:bg-rose-50 active:scale-95"
                    >
                      Clear
                    </button>
                    <button
                      onClick={onSaveCanvas}
                      disabled={saveGraph.isPending}
                      className="inline-flex items-center gap-2 rounded-2xl bg-sky-500 px-5 py-2.5 text-sm font-bold text-white shadow-lg shadow-sky-200 transition hover:bg-sky-600 active:scale-95 disabled:opacity-60"
                    >
                      <Save size={16} />
                      {saveGraph.isPending ? 'Saving…' : 'Save Canvas'}
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
                  // Use mutated state directly for save
                  saveGraph.mutate({
                    campaign_id: id!,
                    nodes: newNodes.map(n => ({
                      id: n.id,
                      node_type: n.type as NodeType,
                      position_x: n.position.x,
                      position_y: n.position.y,
                      data: n.data
                    })),
                    edges: newEdges.map(e => ({
                      source_node_id: e.source,
                      target_node_id: e.target,
                      source_handle: e.sourceHandle || 'default',
                      target_handle: e.targetHandle || 'default'
                    }))
                  })
                }}
                onEditTemplate={setConfigNodeId}
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

      <NodeConfigModal
        nodeId={configNodeId}
        nodes={nodes}
        onClose={() => setConfigNodeId(null)}
        onUpdateNodeData={(nodeId, data) => setNodes(nds => nds.map(n => n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n))}
      />

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

type EmailAccount = { id: string; from_name: string; from_email: string }
type VoiceAgent = { id: string; name: string; retell_agent_id: string }

function NodeConfigModal({
  nodeId,
  nodes,
  onClose,
  onUpdateNodeData,
}: {
  nodeId: string | null
  nodes: Node[]
  onClose: () => void
  onUpdateNodeData: (nodeId: string, data: Record<string, unknown>) => void
}) {
  const open = !!nodeId
  const toast = useToast()
  const node = nodes.find(n => n.id === nodeId)
  const nodeType = node?.data?.node_type as NodeType | undefined

  const templateQuery = useGetTemplate(nodeId || undefined)
  const upsertTemplate = useUpsertTemplate()

  const emailAccountsQuery = useQuery({
    queryKey: ['accounts', 'email'],
    queryFn: async () => (await api.get<EmailAccount[]>('/accounts/email')).data,
    staleTime: 60_000,
  })
  const voiceAgentsQuery = useQuery({
    queryKey: ['accounts', 'voice'],
    queryFn: async () => (await api.get<VoiceAgent[]>('/accounts/voice')).data,
    staleTime: 60_000,
  })

  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [emailAccountId, setEmailAccountId] = useState('')
  const [voiceAgentId, setVoiceAgentId] = useState('')
  const [delayDays, setDelayDays] = useState(1)

  useEffect(() => {
    if (!open) return
    // Load template text
    if (templateQuery.data) {
      setSubject(templateQuery.data.subject ?? '')
      setBody(templateQuery.data.body ?? '')
    } else {
      setSubject('')
      setBody('')
    }
    // Load node-level config from node.data
    if (node?.data) {
      setEmailAccountId((node.data.email_account_id as string) ?? '')
      setVoiceAgentId((node.data.voice_agent_id as string) ?? '')
      setDelayDays((node.data.delay_days as number) ?? 1)
    }
  }, [open, nodeId, templateQuery.data])

  if (!open || !nodeType) return null

  const needsTemplate = nodeType.startsWith('action_') && nodeType !== 'action_linkedin_invite' && nodeType !== 'action_voice'
  const isEmail = nodeType === 'action_email'
  const isVoice = nodeType === 'action_voice'
  const isDelay = nodeType === 'delay'
  const isInvite = nodeType === 'action_linkedin_invite'

  const titleMap: Partial<Record<NodeType, string>> = {
    action_linkedin_invite: 'LinkedIn Invite',
    action_linkedin_dm: 'LinkedIn DM',
    action_email: 'Email',
    action_whatsapp: 'WhatsApp',
    action_instagram: 'Instagram DM',
    action_telegram: 'Telegram',
    action_voice: 'Voice Call',
    delay: 'Delay',
  }

  return (
    <Modal title={`Configure: ${titleMap[nodeType] ?? nodeType}`} open={open} onClose={onClose} width="lg">
      <form
        className="space-y-4"
        onSubmit={async (e) => {
          e.preventDefault()
          // 1. Persist account/agent/delay into node.data in React state
          const dataUpdate: Record<string, unknown> = {}
          if (isEmail && emailAccountId) dataUpdate.email_account_id = emailAccountId
          if (isVoice && voiceAgentId) dataUpdate.voice_agent_id = voiceAgentId
          if (isDelay) dataUpdate.delay_days = delayDays
          if (Object.keys(dataUpdate).length > 0) {
            onUpdateNodeData(nodeId!, dataUpdate)
          }
          // 2. Save template text (only for channels that need it)
          if (needsTemplate && body.trim()) {
            await upsertTemplate.mutateAsync({ node_id: nodeId!, subject: subject || null, body })
          }
          toast.success('Saved.')
          onClose()
        }}
      >
        {isDelay && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Wait (days)</span>
            <input
              type="number"
              min={1}
              value={delayDays}
              onChange={(e) => setDelayDays(Number(e.target.value))}
              className={inputClassName}
              required
            />
          </label>
        )}

        {isEmail && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Email account</span>
            <select value={emailAccountId} onChange={(e) => setEmailAccountId(e.target.value)} className={inputClassName} required>
              <option value="">Select account…</option>
              {(emailAccountsQuery.data ?? []).map(a => (
                <option key={a.id} value={a.id}>{a.from_name} &lt;{a.from_email}&gt;</option>
              ))}
            </select>
          </label>
        )}

        {isVoice && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Voice agent</span>
            <select value={voiceAgentId} onChange={(e) => setVoiceAgentId(e.target.value)} className={inputClassName} required>
              <option value="">Select agent…</option>
              {(voiceAgentsQuery.data ?? []).map(a => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </label>
        )}

        {isEmail && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">Subject</span>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} className={inputClassName} placeholder="Your subject line…" />
          </label>
        )}

        {needsTemplate && (
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-700">
              Message body
              <span className="ml-2 font-normal text-slate-400 text-xs">Use {'{{first_name}}'}, {'{{company}}'}</span>
            </span>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              className={`${inputClassName} min-h-[180px]`}
              placeholder="Hi {{first_name}}, …"
              required
            />
          </label>
        )}

        {isInvite && (
          <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500">
            LinkedIn invite will be sent automatically — no message template needed.
          </p>
        )}

        <button
          type="submit"
          className="w-full rounded-xl bg-sky-500 py-3 font-semibold text-white hover:bg-sky-600 disabled:opacity-60"
          disabled={upsertTemplate.isPending}
        >
          {upsertTemplate.isPending ? 'Saving…' : 'Save'}
        </button>
      </form>
    </Modal>
  )
}

// ── Campaign Settings Tab ──────────────────────────────────────────────────

type LinkedInAccount = { id: string; name: string; unipile_id: string; is_active: boolean }

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
    staleTime: 60_000,
  })
  const assignedQuery = useQuery({
    queryKey: ['campaign-accounts', campaignId],
    queryFn: async () => (await api.get<LinkedInAccount[]>(`/campaigns/${campaignId}/accounts`)).data,
    staleTime: 30_000,
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

  const update = (key: string, val: unknown) => {
    setForm(f => ({ ...f, [key]: val }))
    setDirty(true)
  }

  const onSave = async (e: FormEvent) => {
    e.preventDefault()
    await updateCampaign.mutateAsync({ id: campaignId, payload: form })
    setDirty(false)
    toast.success('Campaign settings saved.')
  }

  const assignedIds = new Set((assignedQuery.data ?? []).map(a => a.id))

  const toggleAccount = async (accountId: string) => {
    const assigned = assignedIds.has(accountId)
    if (assigned) {
      await api.delete(`/campaigns/${campaignId}/accounts/${accountId}`)
    } else {
      await api.post(`/campaigns/${campaignId}/accounts`, { account_id: accountId })
    }
    void queryClient.invalidateQueries({ queryKey: ['campaign-accounts', campaignId] })
  }

  if (campaignQuery.isLoading) return <p className="text-sm text-slate-400">Loading…</p>

  return (
    <div className="space-y-10 max-w-2xl">
      <form onSubmit={onSave} className="space-y-6">
        <h2 className="text-base font-bold text-slate-900">Campaign constants</h2>

        <div className="grid grid-cols-2 gap-4">
          <label className="block">
            <span className={labelCls}>Name</span>
            <input value={form.name ?? ''} onChange={e => update('name', e.target.value)} className={inputClassName} required />
          </label>
          <label className="block">
            <span className={labelCls}>Timezone</span>
            <input value={form.timezone ?? ''} onChange={e => update('timezone', e.target.value)} className={inputClassName} placeholder="Asia/Kolkata" required />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <label className="block">
            <span className={labelCls}>Daily lead cap</span>
            <input type="number" min={1} value={form.daily_lead_cap ?? 50} onChange={e => update('daily_lead_cap', Number(e.target.value))} className={inputClassName} />
          </label>
          <label className="block">
            <span className={labelCls}>Daily invite cap</span>
            <input type="number" min={1} value={form.invite_daily_cap ?? 20} onChange={e => update('invite_daily_cap', Number(e.target.value))} className={inputClassName} />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <label className="block">
            <span className={labelCls}>Active hours start (24h)</span>
            <input type="number" min={0} max={23} value={form.active_hours_start ?? 9} onChange={e => update('active_hours_start', Number(e.target.value))} className={inputClassName} />
          </label>
          <label className="block">
            <span className={labelCls}>Active hours end (24h)</span>
            <input type="number" min={1} max={24} value={form.active_hours_end ?? 18} onChange={e => update('active_hours_end', Number(e.target.value))} className={inputClassName} />
          </label>
        </div>

        <label className="flex items-center gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={!!form.simulation_mode}
            onChange={e => update('simulation_mode', e.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-sky-500"
          />
          <span className="text-sm font-medium text-slate-700">Simulation mode <span className="font-normal text-slate-400">(log actions, don't send)</span></span>
        </label>

        <label className="block">
          <span className={labelCls}>Screening prompt</span>
          <textarea
            value={form.screening_prompt ?? ''}
            onChange={e => update('screening_prompt', e.target.value)}
            rows={4}
            className={`${inputClassName} resize-none`}
            placeholder="Describe who to accept or reject…"
          />
        </label>

        <button
          type="submit"
          disabled={!dirty || updateCampaign.isPending}
          className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-6 py-2.5 text-sm font-bold text-white transition hover:bg-sky-600 disabled:opacity-40"
        >
          <Save size={15} />
          {updateCampaign.isPending ? 'Saving…' : 'Save changes'}
        </button>
      </form>

      <div className="border-t border-slate-100 pt-8">
        <h2 className="mb-4 text-base font-bold text-slate-900">LinkedIn accounts assigned to this campaign</h2>
        {linkedinAccountsQuery.isLoading ? (
          <p className="text-sm text-slate-400">Loading accounts…</p>
        ) : (
          <div className="space-y-2">
            {(linkedinAccountsQuery.data ?? []).map(acct => {
              const on = assignedIds.has(acct.id)
              return (
                <div key={acct.id} className="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-900">{acct.name}</p>
                    <p className="text-xs text-slate-400">{acct.unipile_id}</p>
                  </div>
                  <button
                    onClick={() => toggleAccount(acct.id)}
                    className={`rounded-xl px-4 py-1.5 text-xs font-bold transition ${on ? 'bg-emerald-100 text-emerald-700 hover:bg-rose-50 hover:text-rose-500' : 'bg-slate-200 text-slate-500 hover:bg-sky-50 hover:text-sky-600'}`}
                  >
                    {on ? 'Assigned ✓' : 'Assign'}
                  </button>
                </div>
              )
            })}
            {(linkedinAccountsQuery.data ?? []).length === 0 && (
              <p className="text-sm text-slate-400">No LinkedIn accounts configured yet. Go to Settings → LinkedIn.</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Campaign creation form ─────────────────────────────────────────────────

const labelCls = 'mb-1.5 block text-sm font-medium text-slate-700'

function CampaignForm({ form, onChange, onSubmit, busy, submitLabel }: { form: any, onChange: any, onSubmit: (e: FormEvent) => void, busy: boolean, submitLabel: string }) {
  const update = (key: string, val: any) => onChange({ ...form, [key]: val })
  return (
    <form className="space-y-4" onSubmit={onSubmit}>
      <label className="block">
        <span className={labelCls}>Campaign name</span>
        <input value={form.name} onChange={(e) => update('name', e.target.value)} placeholder="e.g. SaaS Founders Q2" className={inputClassName} required />
      </label>

      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className={labelCls}>Timezone</span>
          <input value={form.timezone} onChange={(e) => update('timezone', e.target.value)} placeholder="Asia/Kolkata" className={inputClassName} required />
        </label>
        <label className="block">
          <span className={labelCls}>Daily lead cap</span>
          <input type="number" min={1} value={form.daily_lead_cap} onChange={(e) => update('daily_lead_cap', Number(e.target.value))} className={inputClassName} />
        </label>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <label className="block">
          <span className={labelCls}>Daily invite cap</span>
          <input type="number" min={1} value={form.invite_daily_cap} onChange={(e) => update('invite_daily_cap', Number(e.target.value))} className={inputClassName} />
        </label>
        <label className="block">
          <span className={labelCls}>Active hours (24h start–end)</span>
          <div className="flex items-center gap-2">
            <input type="number" min={0} max={23} value={form.active_hours_start} onChange={(e) => update('active_hours_start', Number(e.target.value))} className={inputClassName} />
            <span className="text-slate-400">–</span>
            <input type="number" min={1} max={24} value={form.active_hours_end} onChange={(e) => update('active_hours_end', Number(e.target.value))} className={inputClassName} />
          </div>
        </label>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <button type="button" onClick={() => update('sequence_mode', 'sequential')}
          className={`flex flex-col items-center gap-2 rounded-2xl border-2 p-4 transition ${form.sequence_mode === 'sequential' ? 'border-sky-500 bg-sky-50' : 'border-slate-100 bg-slate-50 hover:border-slate-200'}`}>
          <div className={`rounded-lg p-2 ${form.sequence_mode === 'sequential' ? 'bg-sky-500 text-white' : 'bg-white text-slate-400'}`}><Clock size={20} /></div>
          <div className="text-center"><p className="text-sm font-bold text-slate-900">Sequential</p><p className="text-[10px] text-slate-500">Simple linear list</p></div>
        </button>
        <button type="button" onClick={() => update('sequence_mode', 'canvas')}
          className={`flex flex-col items-center gap-2 rounded-2xl border-2 p-4 transition ${form.sequence_mode === 'canvas' ? 'border-sky-500 bg-sky-50' : 'border-slate-100 bg-slate-50 hover:border-slate-200'}`}>
          <div className={`rounded-lg p-2 ${form.sequence_mode === 'canvas' ? 'bg-sky-500 text-white' : 'bg-white text-slate-400'}`}><Zap size={20} /></div>
          <div className="text-center"><p className="text-sm font-bold text-slate-900">Nodal Canvas</p><p className="text-[10px] text-slate-500">Advanced graph flow</p></div>
        </button>
      </div>

      <button type="submit" className="w-full rounded-xl bg-sky-500 py-3 font-semibold text-white hover:bg-sky-600 disabled:opacity-50" disabled={busy}>{submitLabel}</button>
    </form>
  )
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-center">
      <div className="text-xs uppercase tracking-[0.14em] text-slate-400">{label}</div>
      <div className="mt-1 text-xl font-semibold text-slate-900">{value}</div>
    </div>
  )
}

const inputClassName = 'w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none focus:ring-4 focus:ring-sky-100'
