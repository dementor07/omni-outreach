import { useState, useCallback, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
  Connection,
  NodeTypes,
  Handle,
  Position,
  Panel,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  useReactFlow,
  MarkerType,
  ConnectionLineType,
  type EdgeProps,
  type OnNodesChange,
  type OnEdgesChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../api/client';
import { useToast } from '../components/Toast';
import { ArrowLeft, X, Trash2 } from 'lucide-react';

type RetellEdge = {
  id: string;
  destination_node_id: string;
  transition_condition: { type: string; prompt: string };
}

type RetellNode = {
  id: string;
  type: 'conversation' | 'transfer_call' | 'end';
  name: string;
  display_position: { x: number; y: number };
  instruction?: { type: string; text: string };
  edges?: RetellEdge[];
  edge?: RetellEdge;
  transfer_destination?: { type: string; number: string };
  transfer_option?: { type: string; enable_bridge_audio_cue: boolean };
}

type RetellFlow = {
  conversation_flow_id: string;
  global_prompt: string;
  start_node_id: string;
  nodes: RetellNode[];
}

// Conversion helpers

function retellNodesToFlow(nodes: RetellNode[]): Node<RetellNode>[] {
  return nodes.map(n => ({
    id: n.id,
    type: n.type,
    position: { x: n.display_position.x, y: n.display_position.y },
    data: { ...n }
  }));
}

function retellEdgesToFlow(nodes: RetellNode[]): Edge<RetellEdge>[] {
  const rfEdges: Edge<RetellEdge>[] = [];
  nodes.forEach(n => {
    const outgoing = [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])];
    outgoing.forEach(e => {
      rfEdges.push({
        id: e.id,
        source: n.id,
        target: e.destination_node_id,
        label: e.transition_condition?.prompt?.slice(0, 40) ?? '',
        type: 'custom',
        data: e
      });
    });
  });
  return rfEdges;
}

function flowToRetellNodes(rfNodes: Node<RetellNode>[], rfEdges: Edge<RetellEdge>[]): RetellNode[] {
  return rfNodes.map(rn => {
    const data = rn.data;
    const nodeEdges = rfEdges.filter(e => e.source === rn.id);
    
    const retellEdges: RetellEdge[] = nodeEdges.map(e => ({
      id: e.id,
      destination_node_id: e.target,
      transition_condition: e.data?.transition_condition ?? { type: 'prompt', prompt: e.label as string || '' }
    }));

    const updatedNode: RetellNode = {
      ...data,
      display_position: { x: Math.round(rn.position.x), y: Math.round(rn.position.y) },
    };

    if (updatedNode.type === 'conversation') {
      updatedNode.edges = retellEdges;
      delete updatedNode.edge;
    } else if (updatedNode.type === 'transfer_call') {
      updatedNode.edge = retellEdges[0];
      delete updatedNode.edges;
    } else {
      delete updatedNode.edges;
      delete updatedNode.edge;
    }

    return updatedNode;
  });
}

// Custom Node Components

function ConversationNode({ data }: { data: RetellNode }) {
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl px-4 py-3 w-56 shadow-2xl ring-1 ring-white/10">
      <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-slate-500" />
      <p className="text-[10px] font-black text-sky-400 uppercase tracking-widest mb-1.5">{data.name}</p>
      <div className="bg-slate-900/50 rounded-lg p-2 border border-slate-700/50">
        <p className="text-[11px] text-slate-400 line-clamp-2 leading-relaxed">
          {data.instruction?.text || 'No instructions set'}
        </p>
      </div>
      <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-slate-500" />
    </div>
  );
}

function TransferCallNode({ data }: { data: RetellNode }) {
  return (
    <div className="bg-indigo-950 border border-indigo-800 rounded-xl px-4 py-3 w-56 shadow-2xl ring-1 ring-indigo-400/20">
      <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-indigo-500" />
      <p className="text-[10px] font-black text-indigo-300 uppercase tracking-widest mb-1.5">{data.name}</p>
      <div className="bg-indigo-900/30 rounded-lg p-2 border border-indigo-700/50">
        <p className="text-[11px] text-indigo-100 font-bold">
          {data.transfer_destination?.number || 'No number'}
        </p>
      </div>
      <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-indigo-500" />
    </div>
  );
}

function EndNode({ data }: { data: RetellNode }) {
  return (
    <div className="bg-rose-950 border border-rose-800 rounded-xl px-4 py-3 w-48 shadow-2xl ring-1 ring-rose-400/20 text-center">
      <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-rose-500" />
      <p className="text-[10px] font-black text-rose-300 uppercase tracking-widest">{data.name}</p>
    </div>
  );
}

function CustomEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected, label }: EdgeProps) {
  const { deleteElements } = useReactFlow();
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: selected ? '#38bdf8' : '#475569', strokeWidth: selected ? 2 : 1.5 }} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="nodrag nopan"
        >
          {label && (
            <span className="bg-slate-800 border border-slate-700 text-[9px] text-slate-400 px-1.5 py-0.5 rounded-md max-w-[120px] truncate block">
              {label as string}
            </span>
          )}
          {selected && (
            <button
              onClick={(e) => { e.stopPropagation(); deleteElements({ edges: [{ id }] }); }}
              className="mt-0.5 h-4 w-4 flex items-center justify-center rounded-full border border-slate-600 bg-slate-900 text-[10px] font-bold text-slate-400 hover:text-rose-400 hover:border-rose-500 transition mx-auto"
            >
              ×
            </button>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes: NodeTypes = {
  conversation: ConversationNode,
  transfer_call: TransferCallNode,
  end: EndNode,
};

const retellEdgeTypes = { custom: CustomEdge };

const retellDefaultEdgeOptions = {
  type: 'custom',
  markerEnd: { type: MarkerType.ArrowClosed, color: '#475569', width: 18, height: 18 },
};

// Node Config Panel Component

function NodeConfigPanel({
  node,
  allNodes,
  edges,
  onChange,
  onEdgeUpdate,
  onEdgeDestinationChange,
  onClose,
  onDelete
}: {
  node: Node<RetellNode>;
  allNodes: Node<RetellNode>[];
  edges: Edge<RetellEdge>[];
  onChange: (updated: Node<RetellNode>) => void;
  onEdgeUpdate: (edgeId: string, condition: { type: string; prompt: string }) => void;
  onEdgeDestinationChange: (edgeId: string, destinationNodeId: string) => void;
  onClose: () => void;
  onDelete: () => void;
}) {
  const data = node.data;

  const updateData = (updates: Partial<RetellNode>) => {
    onChange({ ...node, data: { ...data, ...updates } });
  };

  return (
    <aside className="w-80 border-l border-slate-800 bg-slate-900 flex flex-col shadow-2xl">
      <div className="flex items-center justify-between p-4 border-b border-slate-800">
        <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-100">Node Settings</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={onDelete}
            className="text-slate-600 hover:text-rose-400 transition-colors"
            title="Delete node"
          >
            <Trash2 size={15} />
          </button>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X size={18} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        <div>
          <label className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2 block">Name</label>
          <input
            value={data.name}
            onChange={(e) => updateData({ name: e.target.value })}
            className="w-full bg-slate-800 border-none rounded-lg px-3 py-2 text-xs text-white focus:ring-2 focus:ring-sky-500/50 outline-none"
          />
        </div>

        <div>
          <label className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2 block">Instructions</label>
          <textarea
            value={data.instruction?.text || ''}
            onChange={(e) => updateData({ instruction: { type: 'prompt', text: e.target.value } })}
            className="w-full bg-slate-800 border-none rounded-lg px-3 py-2 text-xs text-white focus:ring-2 focus:ring-sky-500/50 outline-none min-h-[120px] resize-none"
          />
        </div>

        {data.type === 'transfer_call' && (
          <div>
            <label className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2 block">Phone Number</label>
            <input
              value={data.transfer_destination?.number || ''}
              onChange={(e) => updateData({ transfer_destination: { type: 'predefined', number: e.target.value } })}
              className="w-full bg-slate-800 border-none rounded-lg px-3 py-2 text-xs text-white focus:ring-2 focus:ring-sky-500/50 outline-none"
            />
          </div>
        )}

        {data.type === 'conversation' && (
          <div className="space-y-4 pt-4 border-t border-slate-800">
            <h4 className="text-[9px] font-black uppercase tracking-widest text-slate-500">Outgoing Edges</h4>
            {edges.filter(e => e.source === node.id).map((edge) => (
              <div key={edge.id} className="p-3 bg-slate-800/50 rounded-xl border border-slate-700/50 space-y-3">
                <div>
                  <label className="text-[8px] font-bold uppercase text-slate-600 mb-1 block">Condition</label>
                  <textarea
                    value={edge.data?.transition_condition?.prompt || ''}
                    onChange={(e) => onEdgeUpdate(edge.id, { type: 'prompt', prompt: e.target.value })}
                    className="w-full bg-slate-900 border-none rounded-lg px-2 py-1.5 text-[11px] text-slate-300 focus:ring-1 focus:ring-sky-500 outline-none resize-none"
                  />
                </div>
                <div>
                  <label className="text-[8px] font-bold uppercase text-slate-600 mb-1 block">Destination</label>
                  <select
                    value={edge.target}
                    onChange={(e) => onEdgeDestinationChange(edge.id, e.target.value)}
                    className="w-full bg-slate-900 border-none rounded-lg px-2 py-1.5 text-[11px] text-slate-300 focus:ring-1 focus:ring-sky-500 outline-none"
                  >
                    {allNodes.map((n) => (
                      <option key={n.id} value={n.id}>{n.data.name} ({n.id.slice(0, 4)})</option>
                    ))}
                  </select>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}

interface RetellFlowInnerProps {
  nodes: Node<RetellNode>[];
  edges: Edge<RetellEdge>[];
  onNodesChange: OnNodesChange<Node<RetellNode>>;
  onEdgesChange: OnEdgesChange<Edge<RetellEdge>>;
  onConnect: (params: Connection) => void;
  selectedNode: Node<RetellNode> | null;
  setSelectedNode: (n: Node<RetellNode> | null) => void;
  globalPrompt: string;
  setGlobalPrompt: (v: string) => void;
  handleNodeChange: (n: Node<RetellNode>) => void;
  handleEdgeUpdate: (edgeId: string, condition: { type: string; prompt: string }) => void;
  handleEdgeDestinationChange: (edgeId: string, destinationNodeId: string) => void;
  addNode: (type: RetellNode['type']) => void;
}

function RetellFlowInner({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  selectedNode,
  setSelectedNode,
  globalPrompt,
  setGlobalPrompt,
  handleNodeChange,
  handleEdgeUpdate,
  handleEdgeDestinationChange,
  addNode,
}: RetellFlowInnerProps) {
  const { deleteElements } = useReactFlow();

  return (
    <div className="flex flex-1 overflow-hidden">
      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          edgeTypes={retellEdgeTypes}
          defaultEdgeOptions={retellDefaultEdgeOptions}
          onNodeClick={(_, node) => setSelectedNode(node)}
          onPaneClick={() => setSelectedNode(null)}
          fitView
          className="bg-slate-950"
        >
          <Background color="#334155" gap={20} size={1} />
          <Controls className="!bg-slate-900 !border-slate-800 !fill-slate-400" />
          <MiniMap
            nodeColor={(n) => {
              if (n.type === 'end') return '#9f1239';
              if (n.type === 'transfer_call') return '#312e81';
              return '#1e293b';
            }}
            style={{ backgroundColor: '#0f172a' }}
            maskColor="rgba(2, 6, 23, 0.7)"
          />
          <Panel position="top-right">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-5 shadow-2xl w-80 ring-1 ring-white/5">
              <h4 className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-3">Global System Prompt</h4>
              <textarea
                value={globalPrompt}
                onChange={(e) => setGlobalPrompt(e.target.value)}
                className="w-full bg-slate-800 border-none rounded-xl px-4 py-3 text-xs text-slate-200 focus:ring-2 focus:ring-sky-500/50 outline-none min-h-[160px] resize-none leading-relaxed"
                placeholder="Universal instructions for this agent..."
              />
            </div>
          </Panel>
          <Panel position="bottom-center">
            <div className="flex items-center gap-2 bg-slate-900/95 border border-slate-700 rounded-xl px-3 py-2 shadow-2xl backdrop-blur">
              <span className="text-[9px] font-black uppercase tracking-widest text-slate-500 mr-1">Add Node</span>
              <button
                onClick={() => addNode('conversation')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-slate-500 text-slate-300 text-[10px] font-bold transition-all"
              >
                <span className="w-2 h-2 rounded-full bg-slate-500 inline-block" />
                Conversation
              </button>
              <button
                onClick={() => addNode('transfer_call')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-950 border border-indigo-800 hover:border-indigo-600 text-indigo-300 text-[10px] font-bold transition-all"
              >
                <span className="w-2 h-2 rounded-full bg-indigo-500 inline-block" />
                Transfer
              </button>
              <button
                onClick={() => addNode('end')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-950 border border-rose-900 hover:border-rose-700 text-rose-300 text-[10px] font-bold transition-all"
              >
                <span className="w-2 h-2 rounded-full bg-rose-500 inline-block" />
                End Call
              </button>
            </div>
          </Panel>
        </ReactFlow>
      </div>

      {selectedNode && (
        <NodeConfigPanel
          node={selectedNode}
          allNodes={nodes}
          edges={edges}
          onChange={handleNodeChange}
          onEdgeUpdate={handleEdgeUpdate}
          onEdgeDestinationChange={handleEdgeDestinationChange}
          onClose={() => setSelectedNode(null)}
          onDelete={() => {
            deleteElements({ nodes: [{ id: selectedNode.id }] });
            setSelectedNode(null);
          }}
        />
      )}
    </div>
  );
}

// Main Page Component

export default function RetellFlowEditor() {
  const { id: campaignId, agentId } = useParams<{ id: string; agentId: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [flow, setFlow] = useState<RetellFlow | null>(null);
  const [globalPrompt, setGlobalPrompt] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node<RetellNode>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge<RetellEdge>>([]);
  const [selectedNode, setSelectedNode] = useState<Node<RetellNode> | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/accounts/voice/${agentId}/flow`)
      .then(res => {
        const flowData = res.data as RetellFlow;
        setFlow(flowData);
        setGlobalPrompt(flowData.global_prompt);
        setNodes(retellNodesToFlow(flowData.nodes));
        setEdges(retellEdgesToFlow(flowData.nodes));
      })
      .catch(() => toast.error('Failed to load voice flow'))
      .finally(() => setLoading(false));
  }, [agentId, setNodes, setEdges, toast]);

  const onConnect = useCallback(
    (params: Connection) => {
      const newRetellEdge: RetellEdge = {
        id: `edge-${Date.now()}`,
        destination_node_id: params.target!,
        transition_condition: { type: 'prompt', prompt: '' },
      };
      setEdges((eds) =>
        addEdge({ ...params, id: newRetellEdge.id, data: newRetellEdge, label: '' }, eds)
      );
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id === params.source && n.data.type === 'conversation') {
            return {
              ...n,
              data: {
                ...n.data,
                edges: [...(n.data.edges ?? []), newRetellEdge],
              },
            };
          }
          return n;
        })
      );
    },
    [setEdges, setNodes]
  );

  const handlePublish = async () => {
    if (!flow) return;
    setSaving(true);
    try {
      const updatedNodes = flowToRetellNodes(nodes, edges);
      await api.patch(`/accounts/voice/${agentId}/flow`, {
        ...flow,
        global_prompt: globalPrompt,
        nodes: updatedNodes
      });
      toast.success('Flow published to Retell');
    } catch {
      toast.error('Failed to publish flow');
    } finally {
      setSaving(false);
    }
  };

  const handleNodeChange = (updatedNode: Node<RetellNode>) => {
    setNodes(nds => nds.map(n => n.id === updatedNode.id ? updatedNode : n));
    setSelectedNode(updatedNode);
  };

  const handleEdgeUpdate = useCallback((edgeId: string, condition: { type: string; prompt: string }) => {
    setEdges(eds => eds.map(e =>
      e.id === edgeId
        ? { ...e, label: condition.prompt.slice(0, 40), data: { ...e.data!, transition_condition: condition } }
        : e
    ));
  }, [setEdges]);

  const handleEdgeDestinationChange = useCallback((edgeId: string, destinationNodeId: string) => {
    setEdges(eds => eds.map(e =>
      e.id === edgeId
        ? { ...e, target: destinationNodeId, data: { ...e.data!, destination_node_id: destinationNodeId } }
        : e
    ));
  }, [setEdges]);

  const addNode = useCallback((type: RetellNode['type']) => {
    const id = `node-${Date.now()}`;
    const newRetellNode: RetellNode = {
      id,
      type,
      name: type === 'conversation' ? 'New Conversation' : type === 'transfer_call' ? 'Transfer Call' : 'End Call',
      display_position: { x: 200 + Math.random() * 200, y: 200 + Math.random() * 200 },
      instruction: { type: 'prompt', text: '' },
      ...(type === 'conversation' ? { edges: [] } : {}),
      ...(type === 'transfer_call' ? { transfer_destination: { type: 'predefined', number: '' } } : {}),
    };
    const rfNode: Node<RetellNode> = {
      id,
      type,
      position: newRetellNode.display_position,
      data: { ...newRetellNode },
    };
    setNodes((nds) => [...nds, rfNode]);
    setSelectedNode(rfNode);
  }, [setNodes]);

  if (loading) {
    return (
      <div className="h-screen bg-slate-950 flex items-center justify-center">
        <div className="text-sky-500 font-black uppercase tracking-widest animate-pulse">Loading Flow...</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      <header className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900 shadow-xl z-10">
        <div className="flex items-center gap-6">
          <button 
            onClick={() => navigate(`/campaigns/${campaignId}`)}
            className="flex items-center gap-2 text-slate-400 hover:text-slate-100 transition-all text-[10px] font-black uppercase tracking-widest"
          >
            <ArrowLeft size={16} /> Back to Sequence
          </button>
          <div className="h-6 w-px bg-slate-800" />
          <h1 className="text-xs font-black uppercase tracking-widest text-slate-100">Retell Voice Node Editor</h1>
        </div>
        <button
          onClick={handlePublish}
          disabled={saving}
          className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-[10px] font-black uppercase tracking-widest px-6 py-2.5 rounded-xl transition-all shadow-lg shadow-emerald-900/20 active:translate-y-0.5"
        >
          {saving ? 'Publishing...' : 'Publish to Retell'}
        </button>
      </header>

      <ReactFlowProvider>
        <RetellFlowInner
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          selectedNode={selectedNode}
          setSelectedNode={setSelectedNode}
          globalPrompt={globalPrompt}
          setGlobalPrompt={setGlobalPrompt}
          handleNodeChange={handleNodeChange}
          handleEdgeUpdate={handleEdgeUpdate}
          handleEdgeDestinationChange={handleEdgeDestinationChange}
          addNode={addNode}
        />
      </ReactFlowProvider>
    </div>
  );
}
