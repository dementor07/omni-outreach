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
  Users, Settings as SettingsIcon, Trash2, Play, Target, Layers3, ArrowUp, ArrowDown, X,
  AlertTriangle, CheckCircle2, UserPlus, MessageSquareText,
} from 'lucide-react'
import {
  canvas,
  nodes as nodesApi,
  projections,
  integrations,
  objectives,
  type AudienceContact,
  type Connection as IntegrationConnection,
  type Contact,
  type GraphValidation,
  type Lead,
  type NodeManifest,
  type Objective,
  type WorkflowStatus,
} from '../api/v2'
import { nodeIcon } from '../utils/nodeIcons'
import { visualFor } from '../utils/nodeVisuals'
import { nodeLabel, handleLabel, categoryLabel } from '../utils/nodeLabel'
import { nodeConfigSummary } from '../utils/nodeSummary'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import { useToast } from '../components/Toast'
import NodeConfigPanel from '../components/NodeConfigPanel'
import { useCanvasHistory } from '../hooks/useCanvasHistory'
import Tabs from '../components/Tabs'
import DataTable from '../components/DataTable'
import SequentialBuilder from '../components/SequentialBuilder'
import ObjectivePanel from '../components/ObjectivePanel'
import Select from '../components/Select'
import { ApprovalQueue } from './Approvals'

// Category → icon + accent now lives in utils/nodeVisuals (shared with the
// linear SequentialBuilder so a node looks identical in either view).

// ── Node data shape ────────────────────────────────────────────────────────
interface OmniNodeData extends Record<string, unknown> {
  manifest: NodeManifest
  config: Record<string, unknown>
}
type OmniRfNode = Node<OmniNodeData>

type EnrichmentProvider = 'apollo' | 'hunter' | 'proxycurl'
interface EnrichmentStage {
  provider: EnrichmentProvider
  connection_name: string
}

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
  const summary = nodeConfigSummary(manifest, config)
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
          <p className="truncate text-sm font-bold text-slate-900 dark:text-white">{manifest.display_name || nodeLabel(manifest.type)}</p>
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
                <span className={clsx('mr-3 text-[10px] font-bold uppercase tracking-widest', danger ? 'text-rose-400' : 'text-emerald-500')}>{handleLabel(h.name)}</span>
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
      {/* Base rail. */}
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={{ strokeWidth: selected ? 3 : 2, stroke: selected ? '#6366f1' : '#cbd5e1' }} />
      {/* Animated flow overlay: a dashed stroke marching source->target so the
          canvas reads as a live pipeline, not a static diagram. Brand-coloured
          and slightly thicker when selected. */}
      <path
        d={edgePath}
        fill="none"
        stroke={selected ? '#6366f1' : '#818cf8'}
        strokeWidth={selected ? 2.5 : 1.75}
        strokeLinecap="round"
        strokeDasharray="6 9"
        style={{ animation: 'omni-edge-flow 0.9s linear infinite', opacity: selected ? 0.95 : 0.7 }}
      />
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
  const connectionsQuery = useQuery({ queryKey: ['integrations'], queryFn: () => integrations.list() })
  const validationQuery = useQuery({
    queryKey: ['workflow', id, 'validation'],
    queryFn: () => canvas.validation(id!),
    enabled: !!id && !!detailQuery.data,
  })
  const objectiveQuery = useQuery({
    queryKey: ['objective', id],
    queryFn: () => objectives.get(id!),
    enabled: !!id,
    refetchInterval: (query) => query.state.data?.status === 'pursuing' ? 8000 : false,
  })

  const [rfNodes, setRfNodes, onNodesChangeRaw] = useNodesState<OmniRfNode>([])
  const [rfEdges, setRfEdges, onEdgesChangeRaw] = useEdgesState<Edge>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [viewMode, setViewMode] = useState<'canvas' | 'linear'>('canvas')
  const [showValidation, setShowValidation] = useState(false)
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
    // Handle ids MUST match what OmniNode actually renders, or React Flow
    // silently drops the edge (it can't resolve the endpoint). The node renders
    // its single source handle with id="default" and multi-output handles with
    // id=<handle name>; its target handle has NO id (null). So: pass the source
    // handle through verbatim (incl. "default"), and force the target to null.
    // (The old code nulled "default" sources + kept non-default targets, which
    // dropped every loaded edge — visible as a wired graph showing zero edges.)
    const wired: Edge[] = detailQuery.data.edges.map((e) => ({
      id: e.id,
      source: e.source_node_id,
      target: e.target_node_id,
      sourceHandle: e.source_handle || 'default',
      targetHandle: null,
      type: 'omni',
    }))
    setRfNodes(placed)
    setRfEdges(wired)
    reset()
    pushState(placed, wired)
    setDirty(false)
    // The mount-time fitView runs before the async graph has loaded, so the
    // first node sat clipped at the left edge. Re-fit once the nodes are placed
    // (rAF lets React Flow measure node dimensions first).
    requestAnimationFrame(() => {
      requestAnimationFrame(() => rfInstance.current?.fitView({ padding: 0.35, duration: 300 }))
    })
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
      qc.invalidateQueries({ queryKey: ['workflow', id, 'validation'] })
      toast.success('Campaign plan saved.')
    },
    onError: (error: unknown) => toast.error(error instanceof Error ? error.message : 'The graph could not be saved.'),
  })

  // Run the workflow: seed one root lead per starting source and fire them under
  // one correlation id. Discovered entities fan out into campaign leads.
  const runMut = useMutation({
    mutationFn: () => canvas.run(id!),
    onSuccess: (r) => {
      if (r.sources_failed > 0) {
        toast.error(
          `${r.sources_started} sources started; ${r.sources_failed} failed immediately. ${r.failures.join(' · ')}`,
        )
      } else {
        toast.success(
          r.sources_started > 1
            ? `${r.sources_started} sources started together — ${r.events_published} intents dispatched under one run.`
            : `Run started at ${r.node_type} — ${r.events_published} intent dispatched. Leads will appear shortly.`,
        )
      }
      qc.invalidateQueries({ queryKey: ['workflow-leads', id] })
      qc.invalidateQueries({ queryKey: ['leads'] })
      qc.invalidateQueries({ queryKey: ['workflow', id, 'validation'] })
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

  const addEnrichmentStack = useCallback((stages: EnrichmentStage[]) => {
    const stageManifest = manifestByType.get('ai.enrich')
    const continueManifest = manifestByType.get('flow.continue')
    if (!stageManifest || !continueManifest || stages.length === 0) {
      toast.error('The enrichment building block is unavailable. Reload the node registry and try again.')
      return
    }

    const base = {
      x: 140 + (dropSeq % 4) * 48,
      y: 120 + (dropSeq % 4) * 48,
    }
    dropSeq += 1
    const stageNodes: OmniRfNode[] = stages.map((stage, index) => ({
      id: crypto.randomUUID(),
      type: 'omni',
      position: { x: base.x + index * 270, y: base.y },
      data: {
        manifest: stageManifest,
        config: {
          enrich_source: stage.provider,
          connection_name: stage.connection_name,
          merge_policy: 'fill_missing',
          skip_if_complete: true,
        },
      },
    }))
    const exitNode: OmniRfNode = {
      id: crypto.randomUUID(),
      type: 'omni',
      position: { x: base.x + stages.length * 270, y: base.y },
      data: { manifest: continueManifest, config: {} },
    }
    const insertedNodes = [...stageNodes, exitNode]
    const insertedEdges: Edge[] = stageNodes.flatMap((node, index) => {
      const target = insertedNodes[index + 1]
      return [
        {
          id: crypto.randomUUID(),
          source: node.id,
          target: target.id,
          sourceHandle: 'default',
          targetHandle: null,
          type: 'omni',
        },
        {
          id: crypto.randomUUID(),
          source: node.id,
          target: target.id,
          sourceHandle: 'on_error',
          targetHandle: null,
          type: 'omni',
        },
      ]
    })
    const nextNodes = [...rfNodes, ...insertedNodes]
    const nextEdges = [...rfEdges, ...insertedEdges]
    setRfNodes(nextNodes)
    setRfEdges(nextEdges)
    pushState(nextNodes, nextEdges)
    setDirty(true)
    setSelectedNodeId(exitNode.id)
    requestAnimationFrame(() => rfInstance.current?.fitView({ padding: 0.25, duration: 300 }))
    toast.success(`Added ${stages.length}-source enrichment stack. First source has highest priority; later sources fill gaps.`)
  }, [manifestByType, pushState, rfEdges, rfNodes, setRfEdges, setRfNodes, toast])

  const updateNodeConfig = useCallback((
    nodeId: string,
    config: Record<string, unknown>,
    applyToSameType = false,
    changedFields: string[] = [],
  ) => {
    const sourceType = rfNodes.find((node) => node.id === nodeId)?.data.manifest.type
    setRfNodes((ns) => {
      const next = ns.map((n) => {
        if (n.id === nodeId) return { ...n, data: { ...n.data, config } }
        if (!applyToSameType || !sourceType || n.data.manifest.type !== sourceType) return n

        const propagated = { ...n.data.config }
        for (const field of changedFields) {
          if (Object.prototype.hasOwnProperty.call(config, field)) propagated[field] = config[field]
          else delete propagated[field]
        }
        return { ...n, data: { ...n.data, config: propagated } }
      })
      pushState(next, rfEdges)
      return next
    })
    setDirty(true)
  }, [rfEdges, rfNodes, setRfNodes, pushState])

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
  const selectedWiredOutputHandles = selectedNodeId
    ? rfEdges
        .filter((edge) => edge.source === selectedNodeId)
        .map((edge) => String(edge.sourceHandle ?? 'default'))
    : []

  const flow = (
    <div className={clsx('relative flex h-full overflow-hidden', fullscreen ? 'bg-white dark:bg-slate-950' : 'rounded-2xl border border-slate-200 bg-slate-50/60 dark:border-slate-800 dark:bg-slate-900/50')}>
      {/* Palette as a fixed left rail — never overlaps the canvas/handles. */}
      <NodePalette
        manifests={manifestsQuery.data ?? []}
        loading={manifestsQuery.isLoading}
        connections={connectionsQuery.data ?? []}
        connectionsLoading={connectionsQuery.isLoading}
        onAdd={addNode}
        onAddEnrichmentStack={addEnrichmentStack}
      />
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
          <Panel position="top-left" className="ml-2">
            <ValidationStatus
              validation={validationQuery.data}
              loading={validationQuery.isLoading}
              dirty={dirty}
              open={showValidation}
              onToggle={() => setShowValidation((visible) => !visible)}
              onSelectNode={(nodeId) => {
                setSelectedNodeId(nodeId)
                setShowValidation(false)
              }}
            />
          </Panel>
          <Panel position="top-right" className="flex items-center gap-2">
            <div className="glass-panel flex items-center gap-0.5 rounded-lg border border-white/40 p-0.5 dark:border-white/10">
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
              disabled={dirty || validationQuery.data?.valid_for_run === false}
              title={
                dirty
                  ? 'Save the graph before running'
                  : validationQuery.data?.valid_for_run === false
                    ? 'Fix the plan issues before running'
                    : 'Enroll leads at the starting step(s) and start the pipeline'
              }
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
            connections={connectionsQuery.data ?? []}
            wiredOutputHandles={selectedWiredOutputHandles}
            sameTypeCount={rfNodes.filter((node) => node.data.manifest.type === selectedNode.data.manifest.type).length}
            onSave={(config, applyToSameType, changedFields) => {
              updateNodeConfig(selectedNode.id, config, applyToSameType, changedFields)
              if (applyToSameType && changedFields?.length) {
                toast.success(`Applied ${changedFields.length} changed field${changedFields.length === 1 ? '' : 's'} across this campaign. Save the graph to publish.`)
              }
              setSelectedNodeId(null)
            }}
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
    <div className="flex h-[calc(100vh-90px)] flex-col gap-2" data-screen-label="Campaign builder">
      {/* Compact editor header — a single slim bar (back + name + status + tabs),
          not the tall PageHeader the scrolling pages use. The editor is a
          fixed-viewport canvas tool, so every row above the canvas is height
          stolen from the graph. */}
      <div className="flex flex-col gap-2 border-b border-slate-200/80 pb-2 lg:flex-row lg:items-center lg:justify-between lg:gap-3 dark:border-slate-800">
        <div className="flex min-w-0 items-center gap-2.5">
          <Link to="/campaigns" title="Back to campaigns" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800">
            <ArrowLeft size={16} />
          </Link>
          <h1 className="truncate text-[17px] font-semibold tracking-tight text-slate-900 dark:text-white">{wf?.name ?? 'Campaign'}</h1>
          {wf && (
            <div className="flex shrink-0 items-center gap-2">
              <Badge variant={wf.status === 'active' ? 'success' : wf.status === 'paused' ? 'warning' : 'neutral'} label={wf.status} dot size="xs" />
              {objectiveQuery.data && (
                <GoalStatusChip objective={objectiveQuery.data} onClick={() => setActiveTab('goal')} />
              )}
              <span className="hidden text-[11px] text-slate-400 sm:inline">{wf.timezone} · {rfNodes.length} nodes · {rfEdges.length} edges</span>
              {dirty && <Badge variant="warning" label="unsaved" size="xs" />}
            </div>
          )}
        </div>
        <div className="min-w-0 overflow-x-auto lg:shrink-0">
          <Tabs
            value={activeTab}
            onChange={(v) => setActiveTab(v)}
            items={[
              { value: 'sequence', label: 'Sequence', icon: GitBranch },
              { value: 'audience', label: 'Audience', icon: UserPlus },
              { value: 'goal', label: 'Goal', icon: Target },
              { value: 'leads', label: 'Leads', icon: Users },
              { value: 'messages', label: 'Messages', icon: MessageSquareText },
              { value: 'settings', label: 'Settings', icon: SettingsIcon },
            ]}
          />
        </div>
      </div>

      <div className="flex-1 overflow-hidden">
        <main className="relative h-full overflow-hidden">
          {activeTab === 'sequence' && (
            <div className="flex h-full flex-col">
              {/* Compact toolbar row — the tab already says "Sequence", so the
                  big heading + subtitle were just stealing canvas height. */}
              <div className="mb-2 flex items-center justify-end">
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
                  >Sequence</button>
                </div>
              </div>
              
              <div className="flex-1 overflow-hidden">
                {viewMode === 'canvas' ? (
                  <div className="h-full">{flow}</div>
                ) : (
                  <div className="flex h-full overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900/50">
                    <div className="min-w-0 flex-1 overflow-auto">
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
                        onEditNode={(nodeId) => setSelectedNodeId(nodeId)}
                        isSaving={saveMut.isPending}
                      />
                    </div>
                    {selectedNode && (
                      <div className="w-96 shrink-0 border-l border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
                        <NodeConfigPanel
                          manifest={selectedNode.data.manifest}
                          nodeId={selectedNode.id}
                          initialConfig={selectedNode.data.config}
                          saving={false}
                          connections={connectionsQuery.data ?? []}
                          wiredOutputHandles={selectedWiredOutputHandles}
                          sameTypeCount={rfNodes.filter((node) => node.data.manifest.type === selectedNode.data.manifest.type).length}
                          onSave={(config, applyToSameType, changedFields) => {
                            updateNodeConfig(selectedNode.id, config, applyToSameType, changedFields)
                            if (applyToSameType && changedFields?.length) {
                              toast.success(`Applied ${changedFields.length} changed field${changedFields.length === 1 ? '' : 's'} across this campaign. Save the graph to publish.`)
                            }
                            setSelectedNodeId(null)
                          }}
                          onClose={() => setSelectedNodeId(null)}
                        />
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}
          
          {activeTab === 'goal' && (
            <Card padding="lg" className="h-full overflow-auto">
              <div className="mb-4">
                <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Campaign objective</h2>
                <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">
                  Declare the outcome this campaign pursues. The engine sources, screens, and widens the audience on its own — re-running until the target is reached or your safety bounds are spent.
                </p>
              </div>
              <div className="max-w-2xl">
                {id ? (
                  <ObjectivePanel workflowId={id} />
                ) : (
                  <p className="text-sm text-slate-500">Save the campaign first to set a goal.</p>
                )}
              </div>
            </Card>
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
                  { key: 'identity', header: 'Lead', render: (row: Lead) => <span className="font-medium text-slate-900 dark:text-white">{row.identity || '—'}</span> },
                  { key: 'stage', header: 'Step', render: (row: Lead) => <span className="text-slate-600 dark:text-slate-300">{row.stage || '—'}</span> },
                  { key: 'status', header: 'Status', render: (row: Lead) => <Badge label={row.status || 'active'} asStatus dot /> },
                  { key: 'created_at', header: 'Enrolled', render: (row: Lead) => new Date(row.created_at).toLocaleDateString() },
                ]}
                rows={leadsQuery.data ?? []}
                loading={leadsQuery.isLoading}
              />
            </Card>
          )}

          {activeTab === 'messages' && (
            <Card padding="lg" className="h-full overflow-auto">
              <div className="mb-4">
                <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Pending campaign messages</h2>
                <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">
                  Newest first. Each draft identifies the prospect, the connecting LinkedIn seat, and the evidence available to composition.
                </p>
              </div>
              <ApprovalQueue campaignId={id} />
            </Card>
          )}

          {activeTab === 'audience' && id && <AudiencePanel workflowId={id} />}

          {activeTab === 'settings' && (
            <Card padding="lg" className="h-full overflow-auto">
              <WorkflowSettings
                workflowId={id}
                name={wf?.name ?? ''}
                status={wf?.status ?? 'draft'}
                timezone={wf?.timezone ?? 'UTC'}
                startAt={wf?.start_at ?? null}
                endAt={wf?.end_at ?? null}
                dailyCap={wf?.daily_cap ?? null}
                earliestHour={wf?.earliest_hour ?? null}
                latestHour={wf?.latest_hour ?? null}
                daysOfWeek={wf?.days_of_week ?? null}
                rfNodes={rfNodes}
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

function WorkflowSettings({
  workflowId, name, status, timezone, startAt, endAt, dailyCap, earliestHour, latestHour, daysOfWeek, rfNodes, onSaved
}: {
  workflowId?: string; name: string; status: WorkflowStatus; timezone: string;
  startAt: string | null; endAt: string | null;
  dailyCap: number | null; earliestHour: number | null; latestHour: number | null; daysOfWeek: number[] | null;
  rfNodes: OmniRfNode[];
  onSaved: () => void;
}) {
  const [draftName, setDraftName] = useState(name)
  const [draftStatus, setDraftStatus] = useState<WorkflowStatus>(status)
  const [draftTz, setDraftTz] = useState(timezone)
  const [draftStart, setDraftStart] = useState(isoToLocalInput(startAt))
  const [draftEnd, setDraftEnd] = useState(isoToLocalInput(endAt))
  const [draftCap, setDraftCap] = useState(dailyCap == null ? '' : String(dailyCap))
  const [draftEarliest, setDraftEarliest] = useState(earliestHour == null ? '' : String(earliestHour))
  const [draftLatest, setDraftLatest] = useState(latestHour == null ? '' : String(latestHour))
  const [draftDays, setDraftDays] = useState<number[]>(daysOfWeek || [0, 1, 2, 3, 4])

  useEffect(() => {
    setDraftName(name); setDraftStatus(status); setDraftTz(timezone)
    setDraftStart(isoToLocalInput(startAt)); setDraftEnd(isoToLocalInput(endAt))
    setDraftCap(dailyCap == null ? '' : String(dailyCap))
    setDraftEarliest(earliestHour == null ? '' : String(earliestHour))
    setDraftLatest(latestHour == null ? '' : String(latestHour))
    setDraftDays(daysOfWeek || [0, 1, 2, 3, 4])
  }, [name, status, timezone, startAt, endAt, dailyCap, earliestHour, latestHour, daysOfWeek])

  const toast = useToast()
  const poolQ = useQuery({
    queryKey: ['workflow', workflowId, 'accounts'],
    queryFn: () => canvas.pool(workflowId!),
    enabled: !!workflowId,
  })

  const handleSave = () => {
    // Sender-Account Validation (Pre-flight checklist)
    if (draftStatus === 'active') {
      const messageNodes = rfNodes.filter(n => n.data.manifest.type.startsWith('message.'))
      if (messageNodes.length > 0) {
        // Are there any message nodes without an explicit connection?
        const needsPool = messageNodes.some(n => !n.data.config.connection_name && !n.data.config.sending_account_id)
        
        if (needsPool) {
          const poolAccounts = poolQ.data ?? []
          if (poolAccounts.length === 0) {
            toast.error('Cannot activate campaign: Outbound message nodes require a sender account, but the campaign sender pool is empty.')
            return
          }
        }
      }
    }
    mut.mutate()
  }

  const mut = useMutation({
    mutationFn: () => {
      const body: Parameters<typeof canvas.update>[1] = {
        name: draftName.trim(), status: draftStatus, timezone: draftTz,
        daily_cap: draftCap ? parseInt(draftCap, 10) : null,
        earliest_hour: draftEarliest ? parseInt(draftEarliest, 10) : null,
        latest_hour: draftLatest ? parseInt(draftLatest, 10) : null,
        days_of_week: draftDays,
      }
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
    draftStart !== isoToLocalInput(startAt) || draftEnd !== isoToLocalInput(endAt) ||
    draftCap !== (dailyCap == null ? '' : String(dailyCap)) ||
    draftEarliest !== (earliestHour == null ? '' : String(earliestHour)) ||
    draftLatest !== (latestHour == null ? '' : String(latestHour)) ||
    draftDays.join(',') !== (daysOfWeek || [0,1,2,3,4]).join(',')

  const fieldCls = 'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800'
  const scheduleInvalid = !!draftStart && !!draftEnd && new Date(draftEnd) <= new Date(draftStart)
  const tzOptions = useMemo(() => {
    // Intl.supportedValuesOf isn't in this project's TS lib target yet, so probe it
    // narrowly instead of casting all of Intl to any. Falls back to UTC if absent.
    const intlWithTz = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }
    const supported = intlWithTz.supportedValuesOf?.('timeZone') ?? ['UTC']
    return supported.map((tz) => ({ value: tz, label: tz }))
  }, [])

  const toggleDay = (d: number) => {
    setDraftDays(prev => prev.includes(d) ? prev.filter(x => x !== d) : [...prev, d].sort())
  }
  const dayNames = ['M', 'T', 'W', 'T', 'F', 'S', 'S']

  return (
    <div className="max-w-lg space-y-6">
      <div>
        <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Campaign settings</h2>
        <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">Name, lifecycle status, scheduling timezone, and send window.</p>
      </div>
      
      <label className="block">
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Name</span>
        <input value={draftName} onChange={(e) => setDraftName(e.target.value)} className={fieldCls} />
      </label>
      
      <div className="grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Status</span>
          <Select
            ariaLabel="Workflow status"
            value={draftStatus}
            onChange={(v) => setDraftStatus(v as WorkflowStatus)}
            options={[
              { value: 'draft', label: 'Draft' },
              { value: 'active', label: 'Active' },
              { value: 'paused', label: 'Paused' },
              { value: 'archived', label: 'Archived' },
            ]}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Daily Cap</span>
          <input type="number" placeholder="Unlimited" value={draftCap} onChange={(e) => setDraftCap(e.target.value)} className={fieldCls} />
        </label>
      </div>

      <label className="block">
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Timezone</span>
        <Select 
          ariaLabel="Timezone"
          value={draftTz}
          onChange={v => setDraftTz(String(v))}
          options={tzOptions}
        />
      </label>

      <div>
        <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">Send window</span>
        <div className="mb-3 flex items-center gap-1">
          {dayNames.map((n, i) => {
            const d = i; // Monday=0 … Sunday=6 (matches send_policy.py weekday convention)
            const active = draftDays.includes(d);
            return (
              <button 
                key={d} type="button" onClick={() => toggleDay(d)}
                className={`h-7 w-7 rounded-full text-xs font-semibold ${active ? 'bg-brand-500 text-white' : 'bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500'}`}
              >
                {n}
              </button>
            )
          })}
        </div>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-500">Earliest hour (0-23)</span>
            <input type="number" min="0" max="23" value={draftEarliest} onChange={(e) => setDraftEarliest(e.target.value)} className={fieldCls} placeholder="e.g. 9" />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-500">Latest hour (1-24)</span>
            <input type="number" min="1" max="24" value={draftLatest} onChange={(e) => setDraftLatest(e.target.value)} className={fieldCls} placeholder="e.g. 17" />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-500">Starts (Date)</span>
            <input type="datetime-local" value={draftStart} onChange={(e) => setDraftStart(e.target.value)} className={fieldCls} />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-slate-500">Ends (Date)</span>
            <input type="datetime-local" value={draftEnd} onChange={(e) => setDraftEnd(e.target.value)} className={fieldCls} />
          </label>
        </div>
      </div>

      <Button variant="primary" size="md" icon={Save} onClick={handleSave} isLoading={mut.isPending} disabled={!dirty || !draftName.trim() || scheduleInvalid}>
        Save settings
      </Button>

      <hr className="my-6 border-slate-200 dark:border-slate-800" />
      
      {workflowId && <WorkflowPoolSettings workflowId={workflowId} poolQ={poolQ} />}
    </div>
  )
}

function WorkflowPoolSettings({ workflowId, poolQ }: { workflowId: string, poolQ: any }) {
  const qc = useQueryClient()
  const toast = useToast()

  const accsQ = useQuery({
    queryKey: ['integrations', 'accounts'],
    queryFn: integrations.allAccounts
  })

  const [draftPool, setDraftPool] = useState<Set<string>>(new Set())
  
  useEffect(() => {
    if (poolQ.data) {
      setDraftPool(new Set(poolQ.data.map((a: any) => a.id)))
    }
  }, [poolQ.data])

  const savedPool = new Set((poolQ.data || []).map((a: any) => a.id))
  const isDirty = draftPool.size !== savedPool.size || Array.from(draftPool).some(id => !savedPool.has(id))

  const setMut = useMutation({
    mutationFn: (ids: string[]) => canvas.setPool(workflowId, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workflow', workflowId, 'accounts'] })
      toast.success('Pool updated')
    }
  })

  const toggleAccount = (id: string) => {
    setDraftPool(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const allAccounts = accsQ.data || []

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-[14px] font-semibold text-slate-900 dark:text-white">Sending Accounts Pool</h3>
        {isDirty && (
          <Button 
            variant="primary" 
            size="xs" 
            onClick={() => setMut.mutate(Array.from(draftPool))}
            isLoading={setMut.isPending}
          >
            Save pool
          </Button>
        )}
      </div>
      <p className="text-[12px] text-slate-500 mb-3">Select the accounts this campaign is allowed to send from. If none are selected, it relies on individual node configuration.</p>
      
      <div className="space-y-2 border rounded-md p-3 max-h-64 overflow-auto border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900/50">
        {accsQ.isLoading ? (
          <p className="text-xs text-slate-400">Loading accounts...</p>
        ) : allAccounts.length === 0 ? (
          <p className="text-xs text-slate-400">No accounts available across all integrations.</p>
        ) : (
          allAccounts.map(acc => (
            <label key={acc.id} className="flex items-center gap-2 text-sm cursor-pointer">
              <input 
                type="checkbox" 
                checked={draftPool.has(acc.id)} 
                onChange={() => toggleAccount(acc.id)}
                disabled={setMut.isPending}
                className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
              />
              <span className="font-medium text-slate-700 dark:text-slate-200">
                {acc.display_name || acc.external_identity}
              </span>
              <Badge label={acc.channel_kind} size="xs" variant="neutral" />
            </label>
          ))
        )}
      </div>
    </div>
  )
}

function ValidationStatus({
  validation,
  loading,
  dirty,
  open,
  onToggle,
  onSelectNode,
}: {
  validation?: GraphValidation
  loading: boolean
  dirty: boolean
  open: boolean
  onToggle: () => void
  onSelectNode: (nodeId: string) => void
}) {
  const ready = !dirty && validation?.valid_for_run
  const count = validation?.issues.length ?? 0
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        className={clsx(
          'glass-panel flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs font-semibold shadow-sm',
          ready
            ? 'border-emerald-200 text-emerald-700 dark:border-emerald-900 dark:text-emerald-300'
            : 'border-amber-200 text-amber-700 dark:border-amber-900 dark:text-amber-300',
        )}
      >
        {ready ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
        {loading ? 'Checking plan…' : dirty ? 'Unsaved changes' : ready ? 'Ready to run' : `${count} plan ${count === 1 ? 'issue' : 'issues'}`}
      </button>
      {open && (
        <div className="absolute left-0 top-10 z-50 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl dark:border-slate-700 dark:bg-slate-900">
          <div className="border-b border-slate-100 px-3 py-2.5 dark:border-slate-800">
            <p className="text-xs font-semibold text-slate-800 dark:text-slate-100">Plan check</p>
            <p className="mt-0.5 text-[11px] text-slate-400">
              {dirty ? 'Save to check the latest graph.' : 'Errors block runs. Warnings describe intentional sequence endings.'}
            </p>
          </div>
          <div className="max-h-72 overflow-y-auto p-2">
            {!validation || validation.issues.length === 0 ? (
              <p className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300">
                Every step is configured and reachable.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {validation.issues.map((issue, index) => (
                  <li key={`${issue.code}-${issue.node_id ?? issue.edge_id ?? index}`}>
                    <button
                      type="button"
                      disabled={!issue.node_id}
                      onClick={() => issue.node_id && onSelectNode(issue.node_id)}
                      className={clsx(
                        'w-full rounded-lg px-2.5 py-2 text-left',
                        issue.severity === 'error'
                          ? 'bg-rose-50 text-rose-800 dark:bg-rose-950/30 dark:text-rose-200'
                          : 'bg-amber-50 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200',
                        issue.node_id && 'hover:ring-1 hover:ring-current',
                      )}
                    >
                      <span className="block text-[10px] font-bold uppercase tracking-wide opacity-60">{issue.severity}</span>
                      <span className="mt-0.5 block text-xs leading-snug">{issue.message}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

const GOAL_METRIC_LABELS: Record<Objective['metric'], string> = {
  contacts: 'contacts',
  qualified_leads: 'qualified leads',
  companies: 'companies',
  replies: 'replies',
}

function GoalStatusChip({ objective, onClick }: { objective: Objective; onClick: () => void }) {
  const current = Number(objective.progress.current ?? 0)
  const reached = objective.status === 'reached'
  return (
    <button
      type="button"
      onClick={onClick}
      title="Open campaign goal"
      className={clsx(
        'hidden items-center gap-1.5 rounded-full px-2 py-1 text-[10px] font-semibold md:flex',
        reached
          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
          : 'bg-brand-50 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300',
      )}
    >
      <Target size={11} />
      Goal: {current.toLocaleString()} / {objective.target.toLocaleString()} {GOAL_METRIC_LABELS[objective.metric]}
    </button>
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
    capabilities: [], side_effect: 'read', icon: 'help-circle',
    display_name: '', primary_fields: [], advanced_fields: [],
    visible_in_palette: true,
  }
}

// ── In-canvas palette ────────────────────────────────────────────────────────
function NodePalette({
  manifests,
  loading,
  connections,
  connectionsLoading,
  onAdd,
  onAddEnrichmentStack,
}: {
  manifests: NodeManifest[]
  loading: boolean
  connections: IntegrationConnection[]
  connectionsLoading: boolean
  onAdd: (m: NodeManifest) => void
  onAddEnrichmentStack: (stages: EnrichmentStage[]) => void
}) {
  const [filter, setFilter] = useState('')
  const [showEnrichmentStack, setShowEnrichmentStack] = useState(false)
  // Default COLLAPSED to the slim rail so the canvas gets the full width on load
  // (the palette is only needed while adding nodes). Expand on demand.
  const [open, setOpen] = useState(false)

  const grouped = useMemo(() => {
    const filtered = filter
      ? manifests.filter((m) => m.visible_in_palette !== false && (
        m.type.toLowerCase().includes(filter.toLowerCase())
        || m.summary.toLowerCase().includes(filter.toLowerCase())
        || m.display_name.toLowerCase().includes(filter.toLowerCase())
      ))
      : manifests.filter((m) => m.visible_in_palette !== false)
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
    <div className="absolute left-0 top-0 z-30 flex h-full w-64 flex-col overflow-hidden border-r border-slate-200 bg-white shadow-xl dark:border-slate-800 dark:bg-slate-900">
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
      {!filter && (
        <div className="border-b border-slate-100 px-2 py-2 dark:border-slate-800">
          <p className="px-1 pb-1.5 text-[9px] font-bold uppercase tracking-[0.18em] text-brand-500">Recommended building blocks</p>
          <button
            type="button"
            onClick={() => setShowEnrichmentStack(true)}
            className="w-full rounded-xl border border-brand-100 bg-brand-50/70 p-2.5 text-left transition-colors hover:border-brand-200 hover:bg-brand-50 dark:border-brand-900/60 dark:bg-brand-950/30"
          >
            <span className="flex items-center gap-2 text-xs font-semibold text-slate-800 dark:text-slate-100">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-brand-600 shadow-sm dark:bg-slate-900">
                <Layers3 size={14} />
              </span>
              Enrichment stack
            </span>
            <span className="mt-1 block text-[11px] leading-snug text-slate-500">
              Order connected enrichment sources. Later sources fill only the gaps.
            </span>
          </button>
        </div>
      )}
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
                <p className={clsx('px-2 pb-1 text-[9px] font-bold uppercase tracking-[0.18em]', v.accent)}>{categoryLabel(category)}</p>
                <div className="space-y-0.5">
                  {items.map((m) => {
                    const Icon = nodeIcon(m, v.icon)
                    return (
                      <button
                        key={m.type}
                        type="button"
                        draggable
                        onDragStart={(e) => { e.dataTransfer.setData('application/x-omni-node', m.type); e.dataTransfer.effectAllowed = 'move' }}
                        onClick={() => {
                          onAdd(m)
                          setOpen(false)
                        }}
                        title={m.summary}
                        className="flex w-full cursor-grab items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12px] font-medium text-slate-700 transition-colors hover:bg-slate-50 active:cursor-grabbing dark:text-slate-300 dark:hover:bg-slate-800"
                      >
                        <span className={clsx('flex h-5 w-5 flex-shrink-0 items-center justify-center rounded', v.tint, v.accent)}>
                          <Icon size={12} />
                        </span>
                        <span className="truncate">{m.display_name || nodeLabel(m.type)}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })
        )}
      </div>
      {showEnrichmentStack && (
        <EnrichmentStackDialog
          connections={connections}
          loading={connectionsLoading}
          onClose={() => setShowEnrichmentStack(false)}
          onAdd={(stages) => {
            onAddEnrichmentStack(stages)
            setShowEnrichmentStack(false)
            setOpen(false)
          }}
        />
      )}
    </div>
  )
}

const ENRICHMENT_PROVIDER_ORDER: EnrichmentProvider[] = ['apollo', 'proxycurl', 'hunter']
const ENRICHMENT_PROVIDER_COPY: Record<EnrichmentProvider, { name: string; detail: string }> = {
  apollo: { name: 'Apollo', detail: 'Identity, role, company, and LinkedIn matching' },
  proxycurl: { name: 'Proxycurl', detail: 'Deep LinkedIn profile enrichment' },
  hunter: { name: 'Hunter', detail: 'Professional email discovery' },
}

function EnrichmentStackDialog({
  connections,
  loading,
  onClose,
  onAdd,
}: {
  connections: IntegrationConnection[]
  loading: boolean
  onClose: () => void
  onAdd: (stages: EnrichmentStage[]) => void
}) {
  const providerConnections = useMemo(() => {
    const grouped = new Map<EnrichmentProvider, IntegrationConnection[]>()
    for (const provider of ENRICHMENT_PROVIDER_ORDER) {
      grouped.set(provider, connections.filter((connection) => connection.provider === provider))
    }
    return grouped
  }, [connections])
  const [stages, setStages] = useState<EnrichmentStage[]>([])
  const initialized = useRef(false)
  useEffect(() => {
    if (loading || initialized.current) return
    setStages(ENRICHMENT_PROVIDER_ORDER.flatMap((provider) => {
      const first = connections.find((connection) => connection.provider === provider)
      return first ? [{ provider, connection_name: first.name }] : []
    }))
    initialized.current = true
  }, [connections, loading])

  const missingProviders = ENRICHMENT_PROVIDER_ORDER.filter(
    (provider) => (providerConnections.get(provider)?.length ?? 0) === 0,
  )
  const addableProviders = ENRICHMENT_PROVIDER_ORDER.filter(
    (provider) => (providerConnections.get(provider)?.length ?? 0) > 0
      && !stages.some((stage) => stage.provider === provider),
  )
  const connectedCount = ENRICHMENT_PROVIDER_ORDER.filter(
    (provider) => (providerConnections.get(provider)?.length ?? 0) > 0,
  ).length

  function move(index: number, direction: -1 | 1) {
    const target = index + direction
    if (target < 0 || target >= stages.length) return
    setStages((current) => {
      const next = [...current]
      ;[next[index], next[target]] = [next[target], next[index]]
      return next
    })
  }

  return createPortal(
    <div className="fixed inset-0 z-[10050] flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Build enrichment stack">
      <div className="w-full max-w-xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-slate-900">
        <div className="flex items-start justify-between gap-4 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
          <div>
            <p className="text-base font-semibold text-slate-900 dark:text-white">Build an enrichment stack</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              Put your most trusted source first. Each later source fills missing fields; it never silently replaces a value learned earlier.
            </p>
          </div>
          <button type="button" onClick={onClose} title="Close" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          {loading ? (
            <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-500 dark:bg-slate-800/50">Loading connected enrichment sources…</p>
          ) : stages.length === 0 && connectedCount === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 p-5 text-center dark:border-slate-700">
              <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">Connect an enrichment source first</p>
              <p className="mt-1 text-xs text-slate-500">Connected enrichment APIs will appear here automatically.</p>
              <Link to="/integrations" className="mt-3 inline-flex text-xs font-semibold text-brand-600 hover:text-brand-700">Open integrations</Link>
            </div>
          ) : (
            <>
              <div className="space-y-2">
                {stages.map((stage, index) => {
                  const options = providerConnections.get(stage.provider) ?? []
                  const copy = ENRICHMENT_PROVIDER_COPY[stage.provider]
                  return (
                    <div key={stage.provider} className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                      <span className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-bold text-brand-700 dark:bg-brand-950/50 dark:text-brand-300">
                        {index + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2">
                          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">{copy.name}</span>
                          <span className="truncate text-[11px] text-slate-400">{copy.detail}</span>
                        </div>
                        <select
                          value={stage.connection_name}
                          onChange={(event) => setStages((current) => current.map((item, itemIndex) => (
                            itemIndex === index ? { ...item, connection_name: event.target.value } : item
                          )))}
                          className="mt-1.5 w-full rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700 focus:border-brand-400 focus:outline-none dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
                        >
                          {options.map((connection) => <option key={connection.id} value={connection.name}>{connection.name}</option>)}
                        </select>
                      </div>
                      <div className="flex flex-col gap-1">
                        <button type="button" onClick={() => move(index, -1)} disabled={index === 0} title="Move earlier" className="rounded p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-25 dark:hover:bg-slate-800"><ArrowUp size={13} /></button>
                        <button type="button" onClick={() => move(index, 1)} disabled={index === stages.length - 1} title="Move later" className="rounded p-1 text-slate-400 hover:bg-slate-100 disabled:opacity-25 dark:hover:bg-slate-800"><ArrowDown size={13} /></button>
                      </div>
                      <button type="button" onClick={() => setStages((current) => current.filter((_, itemIndex) => itemIndex !== index))} title={`Remove ${copy.name}`} className="rounded p-1.5 text-slate-300 hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-950/30"><Trash2 size={14} /></button>
                    </div>
                  )
                })}
              </div>
              {addableProviders.length > 0 && (
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11px] font-medium text-slate-400">Add source:</span>
                  {addableProviders.map((provider) => {
                    const connection = providerConnections.get(provider)?.[0]
                    return (
                      <button
                        key={provider}
                        type="button"
                        onClick={() => connection && setStages((current) => [...current, {
                          provider,
                          connection_name: connection.name,
                        }])}
                        className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] font-semibold text-slate-600 hover:border-brand-200 hover:text-brand-600 dark:border-slate-700 dark:text-slate-300"
                      >
                        + {ENRICHMENT_PROVIDER_COPY[provider].name}
                      </button>
                    )
                  })}
                </div>
              )}
              <div className="rounded-xl bg-emerald-50 px-3 py-2.5 text-[11px] leading-relaxed text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-300">
                Provider errors automatically fall through to the next source. Every attempt records the provider, fields received, fields applied, and timestamp.
              </div>
            </>
          )}

          {!loading && missingProviders.length > 0 && stages.length > 0 && (
            <p className="text-[11px] text-slate-400">
              Not connected: {missingProviders.map((provider) => ENRICHMENT_PROVIDER_COPY[provider].name).join(', ')}.{' '}
              <Link to="/integrations" className="font-semibold text-brand-600">Add integrations</Link>
            </p>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-slate-100 px-5 py-3 dark:border-slate-800">
          <p className="text-[11px] text-slate-400">{stages.length} {stages.length === 1 ? 'source' : 'sources'} · fill missing fields</p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
            <Button variant="primary" size="sm" icon={Layers3} disabled={stages.length === 0} onClick={() => onAdd(stages)}>
              Add stack
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}

// OUTBOUND-FIRST-001: attach contacts a campaign reaches when it starts with an
// outbound step. Without an audience, an outbound-rooted campaign can't run.
function AudiencePanel({ workflowId }: { workflowId: string }) {
  const qc = useQueryClient()
  const toast = useToast()
  const [search, setSearch] = useState('')

  const audienceQ = useQuery({
    queryKey: ['audience', workflowId],
    queryFn: () => canvas.audience(workflowId),
  })
  const contactsQ = useQuery({
    queryKey: ['contacts', { q: search, limit: 50 }],
    queryFn: () => projections.contacts({ q: search.trim() || undefined, limit: 50 }),
  })

  const attachedIds = useMemo(
    () => new Set((audienceQ.data ?? []).map((a: AudienceContact) => a.contact_id)),
    [audienceQ.data],
  )

  const addMut = useMutation({
    mutationFn: (contactId: string) => canvas.addAudience(workflowId, [contactId]),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['audience', workflowId] })
      qc.invalidateQueries({ queryKey: ['workflow', workflowId, 'validation'] })
    },
    onError: () => toast.error('Could not add contact to the audience'),
  })
  const removeMut = useMutation({
    mutationFn: (contactId: string) => canvas.removeAudience(workflowId, contactId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['audience', workflowId] })
      qc.invalidateQueries({ queryKey: ['workflow', workflowId, 'validation'] })
    },
  })

  const audience = audienceQ.data ?? []
  const candidates = (contactsQ.data ?? []).filter((c: Contact) => !attachedIds.has(c.id))

  return (
    <div className="grid h-full grid-cols-1 gap-4 overflow-auto p-1 lg:grid-cols-2">
      {/* Attached audience */}
      <Card padding="lg" className="flex flex-col overflow-hidden">
        <div className="mb-3">
          <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">
            Audience <span className="text-slate-400">({audience.length})</span>
          </h2>
          <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">
            The people this campaign reaches. Required when the sequence starts with an outbound
            step (invite / DM / email) instead of a discovery source.
          </p>
        </div>
        {audienceQ.isLoading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
        ) : audience.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-700">
            No audience yet. Add contacts from the right to reach them.
          </div>
        ) : (
          <ul className="space-y-1.5 overflow-auto">
            {audience.map((a: AudienceContact) => (
              <li key={a.contact_id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 dark:border-slate-800">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
                    {[a.first_name, a.last_name].filter(Boolean).join(' ') || a.email || a.linkedin_url || 'Contact'}
                  </p>
                  <p className="truncate text-xs text-slate-500">{a.linkedin_url || a.email || a.company || '—'}</p>
                </div>
                <button
                  type="button"
                  onClick={() => removeMut.mutate(a.contact_id)}
                  title="Remove from audience"
                  aria-label="Remove from audience"
                  className="ml-2 rounded p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-900/30"
                >
                  <X size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Add contacts */}
      <Card padding="lg" className="flex flex-col overflow-hidden">
        <div className="mb-3">
          <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">Add contacts</h2>
          <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">
            Search your CRM and attach people to this campaign. Create new contacts on the Contacts page.
          </p>
        </div>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search contacts by name, email, company…"
          className="mb-3 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
        />
        {contactsQ.isLoading ? (
          <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
        ) : candidates.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-sm text-slate-400 dark:border-slate-700">
            {search.trim() ? 'No matching contacts.' : 'No more contacts to add.'}
          </div>
        ) : (
          <ul className="space-y-1.5 overflow-auto">
            {candidates.map((c: Contact) => (
              <li key={c.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 dark:border-slate-800">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
                    {[c.first_name, c.last_name].filter(Boolean).join(' ') || c.email || c.linkedin_url || 'Contact'}
                  </p>
                  <p className="truncate text-xs text-slate-500">{c.linkedin_url || c.email || c.company || '—'}</p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={addMut.isPending}
                  onClick={() => addMut.mutate(c.id)}
                >
                  <Plus size={14} /> Add
                </Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
