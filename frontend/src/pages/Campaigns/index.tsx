import React, { FormEvent, useEffect, useState, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, Save, Undo2, Redo2, Copy, Trash2, Rocket, Play, Pause, Download, ChevronRight,
  Users, ListTodo, GitBranch, Database, Settings
} from 'lucide-react'

// Layout & UI Components
import Badge from '../../components/Badge'
import Button from '../../components/Button'
import Tabs from '../../components/Tabs'
import PageHeader from '../../components/PageHeader'
import Card from '../../components/Card'
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

  // Auto-open the create modal when arriving with ?new=1 (e.g., from Dashboard).
  useEffect(() => {
    if (!id && searchParams.get('new') === '1') {
      setForm(defaultCampaignForm)
      setCreateOpen(true)
      const next = new URLSearchParams(searchParams)
      next.delete('new')
      setSearchParams(next, { replace: true })
    }
  }, [id, searchParams, setSearchParams])

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
    if (!graphQuery.data) return
    // Backend stores nodes as { id, node_type, position_x, position_y, data }.
    // xyflow expects { id, type, position: {x, y}, data }. Map both directions.
    const apiNodes = (graphQuery.data.nodes as unknown as Array<Record<string, unknown>>) || []
    const apiEdges = (graphQuery.data.edges as unknown as Array<Record<string, unknown>>) || []
    setNodes(apiNodes.map((n) => ({
      id: String(n.id),
      type: (n.node_type as string) || (n.type as string) || 'action_email',
      position: { x: Number(n.position_x ?? 0), y: Number(n.position_y ?? 0) },
      data: (n.data as Record<string, unknown>) || {},
    })) as Node[])
    setEdges(apiEdges.map((e) => ({
      id: String(e.id ?? `${e.source_node_id}-${e.target_node_id}`),
      source: String(e.source_node_id ?? e.source),
      target: String(e.target_node_id ?? e.target),
      sourceHandle: (e.source_handle as string) ?? null,
      targetHandle: (e.target_handle as string) ?? null,
      type: 'custom',
      animated: true,
    })) as Edge[])
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
    // Map xyflow shape -> backend shape before posting.
    const apiNodes = nodes.map((n) => ({
      id: n.id,
      node_type: (n.type as string),
      position_x: n.position?.x ?? 0,
      position_y: n.position?.y ?? 0,
      data: (n.data as Record<string, unknown>) ?? {},
    }))
    const apiEdges = edges.map((e) => ({
      id: e.id,
      source_node_id: e.source,
      target_node_id: e.target,
      source_handle: e.sourceHandle ?? 'default',
      target_handle: e.targetHandle ?? 'default',
    }))
    await saveGraph.mutateAsync({ campaign_id: id!, nodes: apiNodes as any, edges: apiEdges as any })
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
          <div className="flex flex-wrap items-center gap-2">
            <Badge label={campaignQuery.data?.status || 'draft'} asStatus dot />
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
              <div className="flex h-7 rounded-md border border-slate-200 bg-white p-0.5 dark:border-slate-700 dark:bg-slate-900">
                <button
                  type="button"
                  onClick={() => updateCampaign.mutate({ id: id!, payload: { status: 'active' } })}
                  title="Resume campaign"
                  className={`flex items-center gap-1 rounded px-2 text-[11px] font-semibold transition-colors ${
                    campaignQuery.data?.status === 'active'
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                      : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                  }`}
                >
                  <Play size={11} fill="currentColor" /> Resume
                </button>
                <button
                  type="button"
                  onClick={() => updateCampaign.mutate({ id: id!, payload: { status: 'paused' } })}
                  title="Pause campaign"
                  className={`flex items-center gap-1 rounded px-2 text-[11px] font-semibold transition-colors ${
                    campaignQuery.data?.status === 'paused'
                      ? 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                      : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200'
                  }`}
                >
                  <Pause size={11} fill="currentColor" /> Pause
                </button>
              </div>
            )}
            <span className="h-3 w-px bg-slate-200 dark:bg-slate-700" />
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 dark:text-slate-400">
              <span className="text-[10px] uppercase tracking-[0.14em] text-slate-400 dark:text-slate-500">TZ</span>
              {campaignQuery.data?.timezone}
            </span>
            {campaignQuery.data?.simulation_mode && (
              <>
                <span className="h-3 w-px bg-slate-200 dark:bg-slate-700" />
                <Badge label="Simulation" variant="warning" dot />
              </>
            )}
          </div>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              icon={Copy}
              onClick={() => navigate(`/campaigns/${id}/clone`)}
            >
              Clone
            </Button>
            <Button
              variant="danger"
              size="sm"
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
            <Card padding="lg" className="flex h-full flex-col overflow-hidden">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Leads pipeline</h2>
                  <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">Imported and discovered leads flowing through this campaign.</p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    icon={Download}
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
                  >
                    Export CSV
                  </Button>
                  <Button size="sm" variant="primary" icon={Plus} onClick={() => setImportOpen(true)}>
                    Import Leads
                  </Button>
                </div>
              </div>
              <DataTable
                columns={[
                  { key: 'lead', header: 'Lead Name', render: (row) => <div><p className="font-semibold text-slate-900 dark:text-white">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || 'Unknown'}</p><p className="text-xs text-slate-400">{row.company || '—'}</p></div> },
                  { key: 'status', header: 'Status', render: (row) => <Badge label={row.status || 'active'} asStatus dot /> },
                  { key: 'invited_at', header: 'Invited', render: (row) => formatDate(row.invited_at) },
                  { key: 'accepted_at', header: 'Accepted', render: (row) => formatDate(row.accepted_at) },
                  { key: 'replied_at', header: 'Replied', render: (row) => formatDate(row.replied_at) },
                ]}
                rows={leadsQuery.data?.leads || []}
                loading={leadsQuery.isLoading}
              />
            </Card>
          )}

          {activeTab === 'queue' && (
            <Card padding="lg" className="h-full overflow-auto">
              <div className="mb-4">
                <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Sequence queue</h2>
                <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">Tasks scheduled for this campaign across every channel.</p>
              </div>
              <DataTable
                columns={[
                  { key: 'channel', header: 'Channel', render: (row) => <Badge label={row.channel} asChannel /> },
                  { key: 'status', header: 'Status', render: (row) => <Badge label={row.status} asStatus dot /> },
                  { key: 'scheduled_at', header: 'Scheduled', render: (row) => formatDate(row.scheduled_at) },
                ]}
                rows={queueListQuery.data || []}
                loading={queueListQuery.isLoading}
              />
            </Card>
          )}

          {activeTab === 'sequence' && (
            <div className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/50">
              {campaignQuery.data?.sequence_mode === 'canvas' ? (
                <div className="flex flex-1 overflow-hidden">
                  <div className="relative flex-1">
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
                      <Background color="#e2e8f0" gap={24} size={1.4} />
                      <Controls className="!overflow-hidden !rounded-xl !border !border-slate-200 !bg-white !shadow-md dark:!border-slate-700 dark:!bg-slate-900" />
                      <MiniMap
                        className="!overflow-hidden !rounded-xl !border !border-slate-200 !bg-white !shadow-md dark:!border-slate-700 dark:!bg-slate-900"
                        nodeStrokeWidth={3}
                        nodeColor="#fb7185"
                        maskColor="rgba(15, 23, 42, 0.04)"
                        zoomable
                        pannable
                      />
                      <NodeSelector onAdd={addNode} />

                      <Panel position="top-right" className="flex items-center gap-2">
                        <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white/90 p-0.5 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/90">
                          <button
                            type="button"
                            onClick={() => { const h = undo(); if (h) { setNodes(h.nodes); setEdges(h.edges); } }}
                            disabled={!canUndo}
                            title="Undo"
                            className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:opacity-30 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                          >
                            <Undo2 size={14} />
                          </button>
                          <button
                            type="button"
                            onClick={() => { const h = redo(); if (h) { setNodes(h.nodes); setEdges(h.edges); } }}
                            disabled={!canRedo}
                            title="Redo"
                            className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:opacity-30 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
                          >
                            <Redo2 size={14} />
                          </button>
                        </div>
                        <Button
                          size="sm"
                          variant="primary"
                          icon={Save}
                          onClick={handleSaveSequence}
                          isLoading={saveGraph.isPending}
                        >
                          {saveGraph.isPending ? 'Saving' : 'Save sequence'}
                        </Button>
                      </Panel>
                    </ReactFlow>
                  </div>
                  {selectedNodeId && (
                    <div className="z-20 w-96 border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
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
                <div className="flex-1 overflow-auto bg-white p-8 dark:bg-slate-900">
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
            <Card padding="lg" className="h-full overflow-auto">
              <CampaignSourcesPanel campaignId={id!} />
            </Card>
          )}

          {activeTab === 'settings' && (
            <Card padding="lg" className="h-full overflow-auto">
              <CampaignSettings campaignId={id!} />
            </Card>
          )}
        </main>
      </div>

      <Modal title="Import leads" open={importOpen} onClose={() => setImportOpen(false)} width="lg">
         <CsvImport campaignId={id!} onComplete={() => { setImportOpen(false); void leadsQuery.refetch() }} onCancel={() => setImportOpen(false)} />
      </Modal>
    </div>
  )
}
