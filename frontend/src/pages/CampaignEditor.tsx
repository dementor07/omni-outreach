import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useParams, Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ReactFlow, Background, Controls, MiniMap, Panel,
  useNodesState, useEdgesState, addEdge,
  Handle, Position, NodeProps, ConnectionLineType,
  EdgeProps, BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow,
  Node, Edge, Connection, ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { clsx } from 'clsx'
import {
  ArrowLeft, Search, GitBranch, Save, Undo2, Redo2, Maximize2, Minimize2, Plus,
  Users, Settings as SettingsIcon, Trash2, Play,
} from 'lucide-react'
import { canvas, nodes as nodesApi, projections, type Lead, type NodeManifest, type WorkflowStatus } from '../api/v2'
import { nodeIcon } from '../utils/nodeIcons'
import { visualFor } from '../utils/nodeVisuals'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import { useToast } from '../components/Toast'
import NodeConfigPanel from '../components/NodeConfigPanel'
import { useCanvasHistory } from '../hooks/useCanvasHistory'
import Tabs from '../components/Tabs'
import DataTable from '../components/DataTable'
import SequentialBuilder from '../components/SequentialBuilder'

// Category → icon + accent now lives in utils/nodeVisuals (shared with the
// linear SequentialBuilder so a node looks identical in either view).

// A short, human config summary shown on the node body so cards aren't identical.
function configSummary(config: Record<string, unknown>): string | null {
  const keys = Object.keys(config)
  if (keys.length === 0) return null
  // Prefer the most meaningful field.
  const preferred = ['subject_template', 'body_template', 'instruction', 'icp_description', 'new_stage', 'title_template', 'amount', 'connection_name', 'url', 'channel']
  for (const k of preferred) {
    const v = config[k]
    if (typeof v === 'string' && v.trim()) return v.length > 48 ? v.slice(0, 47) + '…' : v
    if (typeof v === 'number') return String(v)
  }
  const first = config[keys[0]]
  return typeof first === 'string' ? first.slice(0, 48) : `${keys.length} fields`
}

// ── Node data shape ────────────────────────────────────────────────────────
interface OmniNodeData extends Record<string, unknown> {
  manifest: NodeManifest
  config: Record<string, unknown>
}
type OmniRfNode = Node<OmniNodeData>

// ── Cycle detection ───────────────────────────────────────────────────────
// flow.for_each is a sharp primitive: every visit spawns the whole collection
// again. A back-edge that lands on a for_each already upstream of the source
// creates infinite recursion (see 2026-06 incident: 113k leads in 2h from one
// mis-wired edge). Refuse such edges at draw time.
function createsForEachCycle(
  source: string,
  target: string,
  nodes: OmniRfNode[],
  edges: Edge[],
): boolean {
  const targetNode = nodes.find((n) => n.id === target)
  if (!targetNode || targetNode.data.manifest.type !== 'flow.for_each') return false
  // Walk upstream from `source` using existing edges; if `target` is reachable,
  // the new edge closes a cycle back into the for_each.
  const incoming = new Map<string, string[]>()
  for (const e of edges) {
    if (!e.source || !e.target) continue
    const list = incoming.get(e.target) ?? []
    list.push(e.source)
    incoming.set(e.target, list)
  }
  const seen = new Set<string>()
  const stack: string[] = [source]
  while (stack.length) {
    const cur = stack.pop() as string
    if (cur === target) return true
    if (seen.has(cur)) continue
    seen.add(cur)
    for (const upstream of incoming.get(cur) ?? []) stack.push(upstream)
  }
  return false
}

// ── Custom node ───────────────────────────────────────────────────────────
function OmniNode({ data, selected }: NodeProps<OmniRfNode>) {
  const { manifest, config } = data
  const v = visualFor(manifest.category)
  const Icon = nodeIcon(manifest, v.icon)
  const summary = configSummary(config)
  const schema = manifest.config_schema as { required?: string[] }
  const required = schema.required ?? []
  const missing = required.filter((k) => {
    const val = config[k]
    return val === undefined || val === null || val === ''
  })
  const ready = missing.length === 0
  const terminal = manifest.output_handles.length === 0
  const multi = manifest.output_handles.length > 1

  return (
    <div className={clsx('relative w-64 rounded-2xl border-2 bg-white text-left shadow-sm transition-all dark:bg-slate-900', selected ? v.ring + ' shadow-md' : 'border-slate-200 hover:border-slate-300 dark:border-slate-800 dark:hover:border-slate-700')}>
      <div className="flex items-center gap-3 p-3">
        <div className={clsx('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', v.tint, v.accent)}>
          <Icon size={20} />
        </div>
        <div className="flex-1 overflow-hidden">
          <p className="truncate text-sm font-bold text-slate-900 dark:text-white">{manifest.type.split('.').slice(1).join('.') || manifest.type}</p>
          <p className="truncate text-xs text-slate-500">{summary ?? manifest.summary}</p>
        </div>
      </div>
      {!ready && (
        <div className="border-t border-slate-100 bg-amber-50/50 px-3 py-2 text-[10px] font-semibold text-amber-600 dark:border-slate-800 dark:bg-amber-950/20">
          Missing required configuration
        </div>
      )}
      <Handle
        type="target"
        position={Position.Left}
        className="!h-5 !w-5 !-translate-x-2.5 !border-2 !border-white !bg-slate-400 !transition-transform hover:!scale-125 hover:!bg-slate-600 dark:!border-slate-900 dark:!bg-slate-500"
      />
      {multi ? (
        <div className="flex flex-col gap-1.5 border-t border-slate-100 bg-slate-50/50 p-2 dark:border-slate-800 dark:bg-slate-900/50">
          {manifest.output_handles.map((h) => {
            const danger = h.name === 'on_error' || h.name === 'rejected' || h.name === 'timeout' || h.name === 'empty' || h.name === 'false'
            return (
              <div key={h.name} className="relative flex items-center justify-end pr-1">
                <span className={clsx('mr-3 text-[10px] font-bold uppercase tracking-widest', danger ? 'text-rose-400' : 'text-emerald-500')}>{h.name}</span>
                <Handle
                  type="source"
                  position={Position.Right}
                  id={h.name}
                  style={{ top: '50%' }}
                  className={clsx(
                    '!h-4 !w-4 !translate-x-2 !border-2 !border-white !transition-transform hover:!scale-125 dark:!border-slate-900',
                    danger ? '!bg-rose-400 hover:!bg-rose-500' : '!bg-emerald-500 hover:!bg-emerald-600',
                  )}
                />
              </div>
            )
          })}
        </div>
      ) : terminal ? null : (
        <Handle
          type="source"
          position={Position.Right}
          id="default"
          className="!h-5 !w-5 !translate-x-2.5 !border-2 !border-white !bg-brand-500 !transition-transform hover:!scale-125 hover:!bg-brand-600 dark:!border-slate-900"
        />
      )}
    </div>
  )
}

function OmniEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, selected }: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })
  const { setEdges } = useReactFlow()
  return (
    <>
      {/* Wide invisible hit path so the edge is easy to select/click. */}
      <path d={edgePath} fill="none" stroke="transparent" strokeWidth={18} className="react-flow__edge-interaction" />
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={{ strokeWidth: selected ? 2.5 : 2, stroke: selected ? '#6366f1' : '#94a3b8' }} />
      {selected && (
        <EdgeLabelRenderer>
          <div style={{ position: 'absolute', transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`, pointerEvents: 'all' }} className="nodrag nopan">
            <button
              type="button"
              title="Delete connection"
              onClick={(e) => { e.stopPropagation(); setEdges((eds) => eds.filter((ed) => ed.id !== id)) }}
              className="flex h-6 w-6 items-center justify-center rounded-full border border-slate-200 bg-white text-rose-500 shadow-sm hover:bg-rose-50 hover:text-rose-600 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

const nodeTypes = { omni: OmniNode }
const edgeTypes = { omni: OmniEdge }
let dropSeq = 0

export default function CampaignEditor() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const toast = useToast()
  const [searchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'sequence')
  const leadsQuery = useQuery({
    queryKey: ['workflow-leads', id],
    queryFn: () => projections.leads({ workflow_id: id!, limit: 200 }),
    enabled: !!id && activeTab === 'leads',
  })

  const detailQuery = useQuery({ queryKey: ['workflow', id], queryFn: () => canvas.get(id!), enabled: !!id })
  const manifestsQuery = useQuery({ queryKey: ['node-manifests'], queryFn: nodesApi.list })

  const [rfNodes, setRfNodes, onNodesChangeRaw] = useNodesState<OmniRfNode>([])
  const [rfEdges, setRfEdges, onEdgesChangeRaw] = useEdgesState<Edge>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [viewMode, setViewMode] = useState<'canvas' | 'linear'>('canvas')
  const { pushState, undo, redo, canUndo, canRedo, reset } = useCanvasHistory()
  const rfInstance = useRef<ReactFlowInstance<OmniRfNode, Edge> | null>(null)

  const manifestByType = useMemo(() => {
    const map = new Map<string, NodeManifest>()
    for (const m of manifestsQuery.data ?? []) map.set(m.type, m)
    return map
  }, [manifestsQuery.data])

  // Wrap xyflow change handlers so any structural change (add/remove/move) flags
  // the graph dirty. Pure selection/dimension churn is ignored so the Save button
  // doesn't light up just from clicking around.
  const onNodesChange = useCallback((changes: Parameters<typeof onNodesChangeRaw>[0]) => {
    onNodesChangeRaw(changes)
    if (changes.some((c) => c.type === 'remove' || c.type === 'add' || c.type === 'position')) setDirty(true)
  }, [onNodesChangeRaw])
  const onEdgesChange = useCallback((changes: Parameters<typeof onEdgesChangeRaw>[0]) => {
    onEdgesChangeRaw(changes)
    if (changes.some((c) => c.type === 'remove' || c.type === 'add')) setDirty(true)
  }, [onEdgesChangeRaw])

  // Load server graph into local xyflow state once (and on explicit reload).
  useEffect(() => {
    if (!detailQuery.data || manifestByType.size === 0) return
    const placed: OmniRfNode[] = detailQuery.data.nodes.map((n) => ({
      id: n.id,
      type: 'omni',
      position: { x: n.position_x, y: n.position_y },
      data: { manifest: manifestByType.get(n.node_type) ?? fallbackManifest(n.node_type), config: n.config },
    }))
    const wired: Edge[] = detailQuery.data.edges.map((e) => ({
      id: e.id,
      source: e.source_node_id,
      target: e.target_node_id,
      sourceHandle: e.source_handle === 'default' ? null : e.source_handle,
      targetHandle: e.target_handle === 'default' ? null : e.target_handle,
      type: 'omni',
    }))
    setRfNodes(placed)
    setRfEdges(wired)
    reset()
    pushState(placed, wired)
    setDirty(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detailQuery.data, manifestByType])

  const saveMut = useMutation({
    mutationFn: () =>
      canvas.saveGraph(id!, {
        nodes: rfNodes.map((n) => ({
          id: n.id,
          node_type: n.data.manifest.type,
          position_x: n.position.x,
          position_y: n.position.y,
          config: n.data.config,
        })),
        edges: rfEdges.map((e) => ({
          id: undefined,
          source_node_id: e.source,
          target_node_id: e.target,
          source_handle: e.sourceHandle ?? 'default',
          target_handle: e.targetHandle ?? 'default',
        })),
      }),
    onSuccess: () => {
      setDirty(false)
      qc.invalidateQueries({ queryKey: ['workflow', id] })
    },
  })

  // Run the workflow: seed a lead at the entry (source) node and fire it. The
  // discovered entities fan out into child leads that surface in the Leads tab.
  const hasSource = useMemo(() => rfNodes.some((n) => n.data.manifest.type.startsWith('source.')), [rfNodes])
  const runMut = useMutation({
    mutationFn: () => canvas.run(id!),
    onSuccess: (r) => {
      toast.success(`Run started at ${r.node_type} — ${r.events_published} intent dispatched. Leads will appear shortly.`)
      qc.invalidateQueries({ queryKey: ['workflow-leads', id] })
      qc.invalidateQueries({ queryKey: ['leads'] })
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : 'Run failed'),
  })

  const onConnect = useCallback((conn: Connection) => {
    if (!conn.source || !conn.target) return
    if (createsForEachCycle(conn.source, conn.target, rfNodes, rfEdges)) {
      // A back-edge that lands on a flow.for_each already in the path melts
      // the system (see incident log: one wrong edge spawned 113k leads).
      // Refuse and tell the user why.
      alert(
        'Cannot create this edge: it would loop back into a flow.for_each ' +
        'that is already upstream. flow.for_each has no recursion guard at ' +
        'the canvas level — use a separate workflow or a flow.condition to ' +
        'short-circuit instead.'
      )
      return
    }
    setRfEdges((eds) => {
      const next = addEdge({ ...conn, type: 'omni' }, eds)
      pushState(rfNodes, next)
      return next
    })
    setDirty(true)
  }, [rfNodes, rfEdges, setRfEdges, pushState])

  const onNodeClick = useCallback((_e: React.MouseEvent, node: Node) => setSelectedNodeId(node.id), [])

  const addNode = useCallback((manifest: NodeManifest, pos?: { x: number; y: number }) => {
    const newNode: OmniRfNode = {
      id: crypto.randomUUID(),
      type: 'omni',
      position: pos ?? { x: 120 + (dropSeq % 5) * 40, y: 80 + (dropSeq % 5) * 40 },
      data: { manifest, config: {} },
    }
    dropSeq += 1
    setRfNodes((ns) => {
      const next = ns.concat(newNode)
      pushState(next, rfEdges)
      return next
    })
    setDirty(true)
    setSelectedNodeId(newNode.id)
  }, [rfEdges, setRfNodes, pushState])

  const updateNodeConfig = useCallback((nodeId: string, config: Record<string, unknown>) => {
    setRfNodes((ns) => {
      const next = ns.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, config } } : n))
      pushState(next, rfEdges)
      return next
    })
    setDirty(true)
  }, [rfEdges, setRfNodes, pushState])

  const deleteNode = useCallback((nodeId: string) => {
    setRfNodes((ns) => ns.filter((n) => n.id !== nodeId))
    setRfEdges((es) => es.filter((e) => e.source !== nodeId && e.target !== nodeId))
    setSelectedNodeId(null)
    setDirty(true)
  }, [setRfNodes, setRfEdges])

  const onNodeDragStop = useCallback(() => { setDirty(true); pushState(rfNodes, rfEdges) }, [rfNodes, rfEdges, pushState])

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    const type = e.dataTransfer.getData('application/x-omni-node')
    const manifest = manifestByType.get(type)
    if (!manifest || !rfInstance.current) return
    const pos = rfInstance.current.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    addNode(manifest, pos)
  }, [manifestByType, addNode])

  const onDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }, [])

  const doUndo = useCallback(() => { const h = undo(); if (h) { setRfNodes(h.nodes as OmniRfNode[]); setRfEdges(h.edges); setDirty(true) } }, [undo, setRfNodes, setRfEdges])
  const doRedo = useCallback(() => { const h = redo(); if (h) { setRfNodes(h.nodes as OmniRfNode[]); setRfEdges(h.edges); setDirty(true) } }, [redo, setRfNodes, setRfEdges])

  // Ctrl/Cmd+Z = undo, Ctrl/Cmd+Shift+Z or Ctrl+Y = redo. Ignored while typing
  // in an input/textarea/contenteditable so node-config fields keep native undo.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey)) return
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      const key = e.key.toLowerCase()
      if (key === 'z' && !e.shiftKey) { e.preventDefault(); doUndo() }
      else if ((key === 'z' && e.shiftKey) || key === 'y') { e.preventDefault(); doRedo() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [doUndo, doRedo])

  if (!id) return null
  const wf = detailQuery.data?.workflow
  const selectedNode = rfNodes.find((n) => n.id === selectedNodeId) ?? null

  const flow = (
    <div className={clsx('relative flex h-full overflow-hidden', fullscreen ? 'bg-white dark:bg-slate-950' : 'rounded-2xl border border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/50')}>
      {/* Palette as a fixed left rail — never overlaps the canvas/handles. */}
      <NodePalette manifests={manifestsQuery.data ?? []} loading={manifestsQuery.isLoading} onAdd={addNode} />
      <div className="relative flex-1" onDrop={onDrop} onDragOver={onDragOver}>
        <ReactFlow
          nodes={rfNodes}
          edges={rfEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onNodeDragStop={onNodeDragStop}
          onPaneClick={() => setSelectedNodeId(null)}
          onInit={(inst) => { rfInstance.current = inst }}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          defaultEdgeOptions={{ type: 'omni' }}
          connectionLineType={ConnectionLineType.Bezier}
          connectionLineStyle={{ strokeWidth: 2.5, stroke: '#6366f1' }}
          connectionRadius={40}
          deleteKeyCode={['Backspace', 'Delete']}
          selectNodesOnDrag={false}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1.4} color="#e2e8f0" />
          <Controls className="!overflow-hidden !rounded-xl !border !border-slate-200 !bg-white !shadow-md dark:!border-slate-700 dark:!bg-slate-900" />
          <MiniMap
            className="!overflow-hidden !rounded-xl !border !border-slate-200 !bg-white !shadow-md dark:!border-slate-700 dark:!bg-slate-900"
            nodeStrokeWidth={3}
            nodeColor={(n) => visualFor((n.data as OmniNodeData)?.manifest?.category ?? 'SOURCE').mini}
            maskColor="rgba(15,23,42,0.04)"
            zoomable
            pannable
          />

          {/* Toolbar */}
          <Panel position="top-right" className="flex items-center gap-2">
            <div className="flex items-center gap-0.5 rounded-lg border border-slate-200 bg-white/90 p-0.5 shadow-sm backdrop-blur dark:border-slate-700 dark:bg-slate-900/90">
              <ToolbarBtn title={fullscreen ? 'Exit full screen' : 'Full screen'} onClick={() => setFullscreen((f) => !f)}>
                {fullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
              </ToolbarBtn>
              <span className="mx-0.5 h-4 w-px bg-slate-200 dark:bg-slate-700" />
              <ToolbarBtn title="Undo" onClick={doUndo} disabled={!canUndo}><Undo2 size={14} /></ToolbarBtn>
              <ToolbarBtn title="Redo" onClick={doRedo} disabled={!canRedo}><Redo2 size={14} /></ToolbarBtn>
            </div>
            <Button size="sm" variant="primary" icon={Save} onClick={() => saveMut.mutate()} isLoading={saveMut.isPending} disabled={!dirty}>
              {dirty ? 'Save' : 'Saved'}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon={Play}
              onClick={() => runMut.mutate()}
              isLoading={runMut.isPending}
              disabled={dirty || !hasSource}
              title={dirty ? 'Save the graph before running' : !hasSource ? 'Add a source node to run' : 'Enroll a lead at the source node and start the pipeline'}
            >
              Run
            </Button>
          </Panel>

          {rfNodes.length === 0 && (
            // bottom-center keeps the hint clear of the top-right toolbar at
            // any canvas width (it used to overlap the Save/Run buttons).
            <Panel position="bottom-center" className="pointer-events-none mb-10">
              <div className="rounded-2xl border border-dashed border-slate-300 bg-white/80 px-6 py-5 text-center shadow-sm dark:border-slate-700 dark:bg-slate-900/80">
                <GitBranch size={20} className="mx-auto text-slate-300" />
                <p className="mt-2 text-sm font-semibold text-slate-700 dark:text-slate-200">Empty canvas</p>
                <p className="mt-0.5 text-xs text-slate-500">Drag a node from the palette, or click one to add it.</p>
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>

      {selectedNode && (
        <div className="z-20 w-96 flex-shrink-0 border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
          <NodeConfigPanel
            manifest={selectedNode.data.manifest}
            nodeId={selectedNode.id}
            initialConfig={selectedNode.data.config}
            saving={false}
            onSave={(config) => { updateNodeConfig(selectedNode.id, config); setSelectedNodeId(null) }}
            onDelete={() => deleteNode(selectedNode.id)}
            onClose={() => setSelectedNodeId(null)}
          />
        </div>
      )}
    </div>
  )

  if (fullscreen) {
    return createPortal(<div className="fixed inset-0 z-[9999] h-screen w-screen">{flow}</div>, document.body)
  }

  return (
    <div className="flex h-[calc(100vh-130px)] flex-col gap-4">
      <PageHeader
        screenLabel="Campaign builder"
        eyebrow="Campaign builder"
        title={wf?.name ?? 'Campaign'}
        description="Manage your multi-channel outreach flows and lead pipelines."
        actions={
          <Link to="/campaigns" className="inline-flex h-9 items-center gap-2 rounded-lg px-3.5 text-sm font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800">
            <ArrowLeft size={15} /> Back to campaigns
          </Link>
        }
        meta={
          wf && (
            <div className="flex items-center gap-2">
              <Badge variant={wf.status === 'active' ? 'success' : wf.status === 'paused' ? 'warning' : 'neutral'} label={wf.status} dot />
              <span className="text-[11px] text-slate-500">{wf.timezone}</span>
              <span className="text-slate-300">·</span>
              <span className="text-[11px] text-slate-500">{rfNodes.length} nodes · {rfEdges.length} edges</span>
              {dirty && <Badge variant="warning" label="unsaved" size="xs" />}
            </div>
          )
        }
      />

      <Tabs
        value={activeTab}
        onChange={(v) => setActiveTab(v)}
        items={[
          { value: 'sequence', label: 'Sequence', icon: GitBranch },
          { value: 'leads', label: 'Leads', icon: Users },
          { value: 'settings', label: 'Settings', icon: SettingsIcon },
        ]}
      />

      <div className="flex-1 overflow-hidden">
        <main className="relative h-full overflow-hidden">
          {activeTab === 'sequence' && (
            <div className="flex h-full flex-col">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Sequence builder</h2>
                  <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">Design your outreach workflow.</p>
                </div>
                <div className="flex bg-slate-100 rounded-lg p-1 dark:bg-slate-800">
                  <button
                    type="button"
                    onClick={() => setViewMode('canvas')} 
                    className={clsx('px-3 py-1 text-xs font-semibold rounded-md transition-colors', viewMode === 'canvas' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white' : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200')}
                  >Canvas</button>
                  <button
                    type="button"
                    onClick={() => setViewMode('linear')} 
                    className={clsx('px-3 py-1 text-xs font-semibold rounded-md transition-colors', viewMode === 'linear' ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-white' : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200')}
                  >Linear</button>
                </div>
              </div>
              
              <div className="flex-1 overflow-hidden">
                {viewMode === 'canvas' ? (
                  <div className="h-full">{flow}</div>
                ) : (
                  <div className="h-full overflow-auto bg-white rounded-2xl border border-slate-200 dark:bg-slate-900/50 dark:border-slate-800">
                    <SequentialBuilder
                      nodes={rfNodes}
                      edges={rfEdges}
                      manifests={manifestsQuery.data ?? []}
                      onChange={(n, e) => {
                        setRfNodes(n)
                        setRfEdges(e)
                        setDirty(true)
                        pushState(n, e)
                      }}
                      onSave={() => saveMut.mutate()}
                      onEditNode={(id) => setSelectedNodeId(id)}
                      isSaving={saveMut.isPending}
                    />
                  </div>
                )}
              </div>
            </div>
          )}
          
          {activeTab === 'leads' && (
            <Card padding="lg" className="flex h-full flex-col overflow-hidden">
              <div className="mb-4">
                <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Leads in this campaign</h2>
                <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">
                  Leads enrolled in this workflow. Add a source node to the sequence to pull leads in.
                </p>
              </div>
              <DataTable
                columns={[
                  { key: 'status', header: 'Status', render: (row: Lead) => <Badge label={row.status || 'active'} asStatus dot /> },
                  { key: 'contact_id', header: 'Contact', render: (row: Lead) => <span className="font-mono text-xs text-slate-500">{row.contact_id?.slice(0, 8) ?? '—'}</span> },
                  { key: 'current_node_id', header: 'Current step', render: (row: Lead) => <span className="font-mono text-xs text-slate-500">{row.current_node_id?.slice(0, 8) ?? '—'}</span> },
                  { key: 'created_at', header: 'Enrolled', render: (row: Lead) => new Date(row.created_at).toLocaleDateString() },
                ]}
                rows={leadsQuery.data ?? []}
                loading={leadsQuery.isLoading}
              />
            </Card>
          )}

          {activeTab === 'settings' && (
            <Card padding="lg" className="h-full overflow-auto">
              <WorkflowSettings
                workflowId={id}
                name={wf?.name ?? ''}
                status={wf?.status ?? 'draft'}
                timezone={wf?.timezone ?? 'UTC'}
                startAt={wf?.start_at ?? null}
                endAt={wf?.end_at ?? null}
                onSaved={() => qc.invalidateQueries({ queryKey: ['workflow', id] })}
              />
            </Card>
          )}
        </main>
      </div>
    </div>
  )
}

// ISO <-> the value a <input type="datetime-local"> expects (local, no tz/secs).
function isoToLocalInput(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
function localInputToIso(local: string): string | null {
  if (!local) return null
  const d = new Date(local)
  return Number.isNaN(d.getTime()) ? null : d.toISOString()
}

function WorkflowSettings({ workflowId, name, status, timezone, startAt, endAt, onSaved }: { workflowId?: string; name: string; status: WorkflowStatus; timezone: string; startAt: string | null; endAt: string | null; onSaved: () => void }) {
  const [draftName, setDraftName] = useState(name)
  const [draftStatus, setDraftStatus] = useState<WorkflowStatus>(status)
  const [draftTz, setDraftTz] = useState(timezone)
  const [draftStart, setDraftStart] = useState(isoToLocalInput(startAt))
  const [draftEnd, setDraftEnd] = useState(isoToLocalInput(endAt))
  useEffect(() => {
    setDraftName(name); setDraftStatus(status); setDraftTz(timezone)
    setDraftStart(isoToLocalInput(startAt)); setDraftEnd(isoToLocalInput(endAt))
  }, [name, status, timezone, startAt, endAt])

  const mut = useMutation({
    mutationFn: () => {
      const body: Parameters<typeof canvas.update>[1] = { name: draftName.trim(), status: draftStatus, timezone: draftTz }
      const startIso = localInputToIso(draftStart)
      const endIso = localInputToIso(draftEnd)
      if (startIso) body.start_at = startIso
      if (endIso) body.end_at = endIso
      return canvas.update(workflowId!, body)
    },
    onSuccess: onSaved,
  })
  const dirty =
    draftName.trim() !== name || draftStatus !== status || draftTz !== timezone ||
    draftStart !== isoToLocalInput(startAt) || draftEnd !== isoToLocalInput(endAt)
  const fieldCls = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800'
  const scheduleInvalid = !!draftStart && !!draftEnd && new Date(draftEnd) <= new Date(draftStart)

  return (
    <div className="max-w-lg space-y-5">
      <div>
        <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Campaign settings</h2>
        <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">Name, lifecycle status, scheduling timezone, and send window.</p>
      </div>
      <label className="block">
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Name</span>
        <input value={draftName} onChange={(e) => setDraftName(e.target.value)} className={fieldCls} />
      </label>
      <label className="block">
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Status</span>
        <select value={draftStatus} onChange={(e) => setDraftStatus(e.target.value as WorkflowStatus)} className={fieldCls}>
          <option value="draft">Draft</option>
          <option value="active">Active</option>
          <option value="paused">Paused</option>
          <option value="archived">Archived</option>
        </select>
      </label>
      <label className="block">
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Timezone</span>
        <input value={draftTz} onChange={(e) => setDraftTz(e.target.value)} placeholder="UTC" className={fieldCls} />
      </label>
      <div>
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Send window <span className="font-normal normal-case text-slate-400">(optional)</span></span>
        <p className="mb-2 text-[12px] text-slate-500 dark:text-slate-400">Outbound sends hold until the start and stop after the end. Leave blank for always-on.</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-500">Starts</span>
            <input type="datetime-local" value={draftStart} onChange={(e) => setDraftStart(e.target.value)} aria-label="Campaign start" className={fieldCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-500">Ends</span>
            <input type="datetime-local" value={draftEnd} onChange={(e) => setDraftEnd(e.target.value)} aria-label="Campaign end" className={fieldCls} />
          </label>
        </div>
        {scheduleInvalid && <p className="mt-1.5 text-[12px] text-rose-600">End must be after start.</p>}
      </div>
      <Button variant="primary" size="md" icon={Save} onClick={() => mut.mutate()} isLoading={mut.isPending} disabled={!dirty || !draftName.trim() || scheduleInvalid}>
        Save settings
      </Button>
    </div>
  )
}

function ToolbarBtn({ title, onClick, disabled, children }: { title: string; onClick: () => void; disabled?: boolean; children: React.ReactNode }) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      disabled={disabled}
      className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900 disabled:opacity-30 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
    >
      {children}
    </button>
  )
}

function fallbackManifest(type: string): NodeManifest {
  return {
    type, category: 'TRANSFORM', summary: 'Unknown node type — registry may have changed.',
    config_schema: {}, output_handles: [{ name: 'default', description: '' }],
    capabilities: [], side_effect: 'READ', icon: 'help-circle',
  }
}

// ── In-canvas palette ────────────────────────────────────────────────────────
function NodePalette({ manifests, loading, onAdd }: { manifests: NodeManifest[]; loading: boolean; onAdd: (m: NodeManifest) => void }) {
  const [filter, setFilter] = useState('')
  const [open, setOpen] = useState(true)

  const grouped = useMemo(() => {
    const filtered = filter
      ? manifests.filter((m) => m.type.toLowerCase().includes(filter.toLowerCase()) || m.summary.toLowerCase().includes(filter.toLowerCase()))
      : manifests
    const map = new Map<string, NodeManifest[]>()
    for (const m of filtered) {
      const arr = map.get(m.category) ?? []
      arr.push(m)
      map.set(m.category, arr)
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [manifests, filter])

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Show node palette"
        className="flex h-full w-11 flex-shrink-0 flex-col items-center gap-2 border-r border-slate-200 bg-white py-3 text-slate-500 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900"
      >
        <Plus size={16} />
        <span className="mt-1 text-[10px] font-bold uppercase tracking-[0.2em] [writing-mode:vertical-rl]">Add node</span>
      </button>
    )
  }

  return (
    <div className="flex h-full w-64 flex-shrink-0 flex-col overflow-hidden border-r border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5 dark:border-slate-800">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">Add node</p>
        <button type="button" onClick={() => setOpen(false)} title="Collapse palette" className="text-slate-300 hover:text-slate-500"><Minimize2 size={12} /></button>
      </div>
      <div className="relative border-b border-slate-100 px-2.5 py-2 dark:border-slate-800">
        <Search size={12} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Search…"
          className="w-full rounded-md border border-slate-200 bg-white py-1.5 pl-7 pr-2 text-xs focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800"
        />
      </div>
      <div className="flex-1 space-y-3 overflow-y-auto px-1.5 py-2">
        {loading ? (
          <p className="px-2 text-xs text-slate-500">Loading…</p>
        ) : grouped.length === 0 ? (
          <p className="px-2 text-xs text-slate-400">No matching nodes</p>
        ) : (
          grouped.map(([category, items]) => {
            const v = visualFor(category)
            return (
              <div key={category}>
                <p className={clsx('px-2 pb-1 text-[9px] font-bold uppercase tracking-[0.18em]', v.accent)}>{category}</p>
                <div className="space-y-0.5">
                  {items.map((m) => {
                    const Icon = nodeIcon(m, v.icon)
                    return (
                      <button
                        key={m.type}
                        type="button"
                        draggable
                        onDragStart={(e) => { e.dataTransfer.setData('application/x-omni-node', m.type); e.dataTransfer.effectAllowed = 'move' }}
                        onClick={() => onAdd(m)}
                        title={m.summary}
                        className="flex w-full cursor-grab items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12px] font-medium text-slate-700 transition-colors hover:bg-slate-50 active:cursor-grabbing dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        <span className={clsx('flex h-5 w-5 flex-shrink-0 items-center justify-center rounded', v.tint, v.accent)}>
                          <Icon size={12} />
                        </span>
                        <span className="truncate">{m.type.split('.').slice(1).join('.') || m.type}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
