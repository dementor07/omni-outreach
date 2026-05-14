import React, { FormEvent, useEffect, useState, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Save, Undo2, Redo2, Copy, Trash2, Rocket, Play, Pause, Download, ChevronRight } from 'lucide-react'

// Layout & UI Components
import Badge from '../../components/Badge'
import DataTable from '../../components/DataTable'
import Modal from '../../components/Modal'
import SequentialBuilder from '../../components/SequentialBuilder'
import { useToast } from '../../components/Toast'
import { formatDate } from '../../lib/time'
import { api } from '../../api/client'
import CsvImport from '../../components/CsvImport'

// Hooks
import { useCanvasHistory } from '../../hooks/useCanvasHistory'
import {
  useCampaignStats,
  useCreateCampaign,
  useDeleteCampaign,
  useCloneCampaign,
  useGetCampaign,
  useListCampaigns,
  useUpdateCampaign,
} from '../../hooks/useCampaigns'
import { useListLeads } from '../../hooks/useLeads'
import { useQueueList } from '../../hooks/useQueue'
import { useGetGraph, useSaveGraph } from '../../hooks/useSequenceSteps'

// React Flow
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  addEdge,
  Connection,
  useReactFlow,
  ConnectionLineType,
  Panel,
  Node,
  Edge,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

// Modular Shredded Components
import { CampaignTab, CampaignPayload } from './types'
import { nodeTypes } from './components/Canvas/Nodes'
import { CustomEdge, TelemetryEdge } from './components/Canvas/CustomEdge'
import { NodeSelector } from './components/Canvas/NodeSelector'
import { ConfigSidebar } from './components/Sidebar/ConfigSidebar'
import { CampaignSourcesPanel } from './components/Panels/CampaignSourcesPanel'
import { CampaignSettings } from './components/Panels/CampaignSettings'
import { CampaignForm } from './components/Panels/CampaignForm'

const edgeTypes = { custom: CustomEdge, telemetry: TelemetryEdge }

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

export default function Campaigns() {
  const navigate = useNavigate()
  const { id } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const activeTab = (searchParams.get('tab') as CampaignTab | null) || 'leads'
  const toast = useToast()
  const queryClient = useQueryClient()

  const campaignsQuery = useListCampaigns()
  const campaignQuery = useGetCampaign(id)
  const statsQuery = useCampaignStats(id)
  const createCampaign = useCreateCampaign()
  const updateCampaign = useUpdateCampaign()
  const deleteCampaign = useDeleteCampaign()

  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<CampaignPayload>(defaultCampaignForm)
  const [importOpen, setImportOpen] = useState(false)

  // Sequence / Canvas State
  const graphQuery = useGetGraph(id || undefined)
  const saveGraph = useSaveGraph()
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([])
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const { pushState, undo, redo, canUndo, canRedo } = useCanvasHistory()

  const leadsQuery = useListLeads(id)
  const queueListQuery = useQueueList({ campaignId: id, limit: 50 })

  useEffect(() => {
    if (graphQuery.data) {
      setNodes(graphQuery.data.nodes as any[])
      setEdges(graphQuery.data.edges as any[])
    }
  }, [graphQuery.data, setNodes, setEdges])

  const onConnect = useCallback((params: Connection) => {
    const newEdge = { ...params, type: 'custom', animated: true } as Edge
    setEdges((eds) => addEdge(newEdge, eds))
    pushState(nodes, addEdge(newEdge, edges))
  }, [setEdges, nodes, edges, pushState])

  const onNodeClick = (_: any, node: any) => setSelectedNodeId(node.id)

  const addNode = (type: any) => {
    const newNode = {
      id: crypto.randomUUID(),
      type,
      position: { x: 400, y: 100 },
      data: { node_type: type },
    } as Node
    const nextNodes = nodes.concat(newNode)
    setNodes(nextNodes)
    pushState(nextNodes, edges)
  }

  const updateNodeData = (nodeId: string, data: any) => {
    const nextNodes = nodes.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...data } } : n))
    setNodes(nextNodes)
    pushState(nextNodes, edges)
  }

  const deleteNode = (nodeId: string) => {
    const nextNodes = nodes.filter((n) => n.id !== nodeId)
    const nextEdges = edges.filter((e) => e.source !== nodeId && e.target !== nodeId)
    setNodes(nextNodes)
    setEdges(nextEdges)
    setSelectedNodeId(null)
    pushState(nextNodes, nextEdges)
  }

  const handleSaveSequence = async () => {
    await saveGraph.mutateAsync({ campaign_id: id!, nodes: nodes as any, edges: edges as any })
    toast.success('Sequence saved')
  }

  if (!id) {
    return (
      <div className="space-y-6">
        <PageHeader
          screenLabel="Campaigns"
          eyebrow="Outreach"
          title="Campaigns"
          description="Manage your multi-channel outreach flows and lead pipelines."
          actions={
            <Button
              variant="primary"
              size="md"
              icon={Plus}
              onClick={() => { setForm(defaultCampaignForm); setCreateOpen(true) }}
            >
              New Campaign
            </Button>
          }
        />

        <section className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {campaignsQuery.data?.map((c) => (
            <Card
              key={c.id}
              padding="lg"
              className="group cursor-pointer transition-all hover:border-brand-200 hover:shadow-xl hover:shadow-brand-500/5 active:scale-[0.98]"
              onClick={() => navigate(`/campaigns/${c.id}`)}
            >
              <div className="flex items-start justify-between">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50 text-slate-400 transition-colors group-hover:bg-brand-50 group-hover:text-brand-500">
                  <Rocket size={24} />
                </div>
                <Badge label={c.status || 'active'} asStatus />
              </div>
              <h3 className="mt-6 text-lg font-bold text-slate-900 dark:text-white">{c.name}</h3>
              <p className="mt-1 text-sm text-slate-500 line-clamp-1">{c.timezone} • {c.sequence_mode}</p>
              <div className="mt-8 flex items-center justify-between border-t border-slate-50 pt-4 text-xs font-bold uppercase tracking-widest text-slate-400 transition-colors group-hover:text-brand-600 dark:border-slate-800">
                View detail <ChevronRight size={14} />
              </div>
            </Card>
          ))}
        </section>

        <Modal title="Create Campaign" open={createOpen} onClose={() => setCreateOpen(false)}>
          <CampaignForm
            form={form}
            onChange={setForm}
            busy={createCampaign.isPending}
            submitLabel="Create Campaign"
            onSubmit={async (e: FormEvent) => {
              e.preventDefault()
              const c = await createCampaign.mutateAsync(form)
              setCreateOpen(false)
              navigate(`/campaigns/${c.id}`)
            }}
          />
        </Modal>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-120px)] flex-col gap-6">
      <PageHeader
        screenLabel="Campaign detail"
        title={campaignQuery.data?.name || 'Campaign detail'}
        eyebrow="Campaigns"
        meta={
          <div className="flex items-center gap-3">
            <Badge label={campaignQuery.data?.status || 'draft'} asStatus />
            {campaignQuery.data?.status === 'draft' ? (
              <Button
                variant="primary"
                size="xs"
                icon={Rocket}
                onClick={() => updateCampaign.mutate({ id: id!, payload: { status: 'active' } })}
              >
                Launch
              </Button>
            ) : (
              <div className="flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 shadow-inner dark:border-slate-800 dark:bg-slate-900">
                <button
                  onClick={() => updateCampaign.mutate({ id: id!, payload: { status: 'active' } })}
                  title="Resume Campaign"
                  className={`rounded-md p-1 transition-all ${campaignQuery.data?.status === 'active' ? 'bg-white text-emerald-600 shadow-sm dark:bg-slate-800' : 'text-slate-400 hover:text-slate-600'}`}
                >
                  <Play size={12} fill="currentColor" />
                </button>
                <button
                  onClick={() => updateCampaign.mutate({ id: id!, payload: { status: 'paused' } })}
                  title="Pause Campaign"
                  className={`rounded-md p-1 transition-all ${campaignQuery.data?.status === 'paused' ? 'bg-white text-amber-600 shadow-sm dark:bg-slate-800' : 'text-slate-400 hover:text-slate-600'}`}
                >
                  <Pause size={12} fill="currentColor" />
                </button>
              </div>
            )}
            <span className="text-slate-300 text-xs dark:text-slate-700">|</span>
            <span className="text-xs text-slate-500">{campaignQuery.data?.timezone}</span>
            {campaignQuery.data?.simulation_mode && <Badge label="Simulation" variant="warning" />}
          </div>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="md"
              icon={Copy}
              onClick={() => navigate(`/campaigns/${id}/clone`)}
            >
              Clone
            </Button>
            <Button
              variant="danger"
              size="md"
              icon={Trash2}
              onClick={() => { if (window.confirm('Delete this campaign?')) { deleteCampaign.mutate(id!); navigate('/campaigns') } }}
            >
              Delete
            </Button>
          </div>
        }
      />

      <Tabs
        value={activeTab}
        onChange={(v) => setSearchParams({ tab: v })}
        items={[
          { value: 'leads', label: 'Leads', icon: Users },
          { value: 'queue', label: 'Queue', icon: ListTodo },
          { value: 'sequence', label: 'Sequence', icon: GitBranch },
          { value: 'sources', label: 'Sources', icon: Database },
          { value: 'settings', label: 'Settings', icon: Settings },
        ]}
      />

      <div className="flex-1 overflow-hidden">
        <main className="relative h-full overflow-hidden">
          {activeTab === 'leads' && (
            <div className="h-full flex flex-col rounded-2xl border border-slate-200 bg-white p-8 shadow-sm overflow-hidden">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-slate-900 uppercase tracking-tight">Leads Pipeline</h2>
                <div className="flex gap-2">
                  <button
                    onClick={async () => {
                      const { data } = await api.get(`/leads/export?campaign_id=${id}`, { responseType: 'blob' })
                      const url = window.URL.createObjectURL(new Blob([data]))
                      const link = document.createElement('a')
                      link.href = url
                      link.setAttribute('download', `leads_${id}.csv`)
                      document.body.appendChild(link)
                      link.click()
                      link.remove()
                    }}
                    className="btn-tactile border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50 flex items-center gap-2"
                  >
                    <Download size={13} />
                    Export CSV
                  </button>
                  <button onClick={() => setImportOpen(true)} className="btn-tactile border border-slate-200 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-50">Import Leads</button>
                </div>
              </div>
              <DataTable
                columns={[
                  { key: 'lead', header: 'Lead Name', render: (row) => <div><p className="font-bold text-slate-900">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || 'Unknown'}</p><p className="text-xs text-slate-400">{row.company || '—'}</p></div> },
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
            <div className="h-full overflow-auto rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
              <h2 className="mb-6 text-lg font-semibold text-slate-900 uppercase tracking-tight">Sequence Queue</h2>
              <DataTable
                columns={[
                  { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                  { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus /> },
                  { key: 'scheduled_at', header: 'Scheduled', render: (row) => formatDate(row.scheduled_at) },
                ]}
                rows={queueListQuery.data || []}
                loading={queueListQuery.isLoading}
              />
            </div>
          )}

          {activeTab === 'sequence' && (
            <div className="h-full flex flex-col rounded-2xl border border-slate-200 bg-slate-50 shadow-inner overflow-hidden relative">
              {campaignQuery.data?.sequence_mode === 'canvas' ? (
                <div className="flex-1 flex overflow-hidden">
                  <div className="flex-1 relative">
                    <ReactFlow
                      nodes={nodes}
                      edges={edges}
                      onNodesChange={onNodesChange}
                      onEdgesChange={onEdgesChange}
                      onConnect={onConnect}
                      onNodeClick={onNodeClick}
                      nodeTypes={nodeTypes}
                      edgeTypes={edgeTypes}
                      defaultEdgeOptions={{ type: 'custom' }}
                      connectionLineType={ConnectionLineType.Bezier}
                      fitView
                    >
                      <Background color="#cbd5e1" gap={20} />
                      <Controls className="!bg-white !border-slate-200 !shadow-xl !rounded-xl overflow-hidden" />
                      <MiniMap className="!bg-white !border-slate-200 !shadow-xl !rounded-2xl" nodeStrokeWidth={3} zoomable pannable />
                      <NodeSelector onAdd={addNode} />
                      
                      <Panel position="top-right" className="flex gap-2">
                        <div className="flex items-center gap-1 rounded-2xl border border-slate-200 bg-white/80 backdrop-blur-md p-1 shadow-xl">
                          <button onClick={() => { const h = undo(); if (h) { setNodes(h.nodes); setEdges(h.edges); } }} disabled={!canUndo} className="p-2.5 rounded-xl hover:bg-slate-50 disabled:opacity-20 transition-all"><Undo2 size={16} /></button>
                          <button onClick={() => { const h = redo(); if (h) { setNodes(h.nodes); setEdges(h.edges); } }} disabled={!canRedo} className="p-2.5 rounded-xl hover:bg-slate-50 disabled:opacity-20 transition-all"><Redo2 size={16} /></button>
                        </div>
                        <button
                          onClick={handleSaveSequence}
                          disabled={saveGraph.isPending}
                          className="flex items-center gap-2 rounded-2xl bg-slate-900 px-5 py-2.5 text-xs font-black uppercase tracking-widest text-white shadow-xl transition hover:bg-slate-800 disabled:opacity-50 active:scale-95"
                        >
                          <Save size={14} /> {saveGraph.isPending ? 'Saving...' : 'Save Sequence'}
                        </button>
                      </Panel>
                    </ReactFlow>
                  </div>
                  {selectedNodeId && (
                    <div className="w-96 bg-white border-l border-slate-200 shadow-2xl z-20">
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
              ) : (
                <div className="flex-1 overflow-auto bg-white p-8">
                   <SequentialBuilder 
                     nodes={nodes} 
                     edges={edges} 
                     onSave={handleSaveSequence}
                     onEditTemplate={(nodeId) => setSelectedNodeId(nodeId)}
                   />
                </div>
              )}
            </div>
          )}

          {activeTab === 'sources' && (
            <div className="h-full overflow-auto rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
              <CampaignSourcesPanel campaignId={id!} />
            </div>
          )}

          {activeTab === 'settings' && (
            <div className="h-full overflow-auto rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
              <CampaignSettings campaignId={id!} />
            </div>
          )}
        </main>
      </div>

      <Modal title="Import leads" open={importOpen} onClose={() => setImportOpen(false)} width="lg">
         <CsvImport campaignId={id!} onComplete={() => { setImportOpen(false); void leadsQuery.refetch() }} onCancel={() => setImportOpen(false)} />
      </Modal>
    </div>
  )
}
