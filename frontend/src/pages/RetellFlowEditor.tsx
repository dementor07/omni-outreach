import { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Node,
  Edge,
  addEdge,
  useNodesState,
  useEdgesState,
  Background,
  Controls,
  Connection,
  NodeTypes,
  Handle,
  Position,
  NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../api/client';
import { useToast } from '../components/Toast';
import { X, Save, ArrowLeft, Phone, Share2, LogOut } from 'lucide-react';

interface RetellNode {
  id: string;
  type: 'conversation' | 'transfer_call' | 'end';
  name: string;
  display_position: { x: number; y: number };
  instruction?: { type: string; text: string };
  edges?: RetellEdge[];
  edge?: RetellEdge;
  transfer_destination?: { type: string; number: string };
  transfer_option?: any;
}

interface RetellEdge {
  id: string;
  destination_node_id: string;
  transition_condition?: { type: string; prompt: string };
}

interface RetellFlow {
  conversation_flow_id: string;
  global_prompt: string;
  start_node_id: string;
  nodes: RetellNode[];
}

function retellFlowToReactFlow(flow: RetellFlow): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = flow.nodes.map(n => ({
    id: n.id,
    type: 'retellNode',
    position: { x: n.display_position.x, y: n.display_position.y },
    data: { retellNode: n },
  }));

  const edges: Edge[] = [];
  for (const n of flow.nodes) {
    const outEdges = [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])];
    for (const e of outEdges) {
      edges.push({
        id: e.id,
        source: n.id,
        target: e.destination_node_id,
        label: e.transition_condition?.prompt
          ? e.transition_condition.prompt.slice(0, 40)
          : undefined,
        type: 'default',
      });
    }
  }
  return { nodes, edges };
}

function reactFlowToRetellNodes(rfNodes: Node[], rfEdges: Edge[], originalNodes: RetellNode[]): RetellNode[] {
  const origMap = new Map(originalNodes.map(n => [n.id, n]));

  return rfNodes.map(rfNode => {
    const orig = origMap.get(rfNode.id) ?? rfNode.data.retellNode as RetellNode;
    const outEdges = rfEdges
      .filter(e => e.source === rfNode.id)
      .map(e => ({
        id: e.id,
        destination_node_id: e.target,
        transition_condition: orig.edges?.find(oe => oe.id === e.id)?.transition_condition
          ?? orig.edge?.transition_condition
          ?? { type: 'prompt', prompt: '' },
      }));

    const updated: RetellNode = {
      ...orig,
      display_position: { x: Math.round(rfNode.position.x), y: Math.round(rfNode.position.y) },
    };

    if (updated.type === 'end') {
      delete (updated as any).edges;
      delete (updated as any).edge;
    } else if (outEdges.length === 1 && orig.edge !== undefined) {
      updated.edge = outEdges[0];
      delete updated.edges;
    } else {
      updated.edges = outEdges;
      delete updated.edge;
    }

    return updated;
  });
}

const RetellNodeUI = ({ data, selected }: NodeProps) => {
  const node = data.retellNode as RetellNode;
  const isStart = false; // We could pass this in data if needed

  return (
    <div className={`min-w-[200px] bg-slate-900 border-2 rounded-xl p-4 shadow-2xl transition-all ${selected ? 'border-sky-500 ring-4 ring-sky-500/20' : 'border-slate-800'}`}>
      <Handle type="target" position={Position.Top} className="!bg-slate-700 !border-slate-900" />
      
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-lg ${
          node.type === 'conversation' ? 'bg-sky-500/10 text-sky-400' :
          node.type === 'transfer_call' ? 'bg-emerald-500/10 text-emerald-400' :
          'bg-rose-500/10 text-rose-400'
        }`}>
          {node.type === 'conversation' && <Phone size={14} />}
          {node.type === 'transfer_call' && <Share2 size={14} />}
          {node.type === 'end' && <LogOut size={14} />}
        </div>
        <div>
          <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">{node.type}</p>
          <p className="text-sm font-bold text-white">{node.name}</p>
        </div>
      </div>

      {node.instruction && (
        <p className="text-[10px] text-slate-400 line-clamp-2 italic bg-slate-800/50 p-2 rounded border border-slate-700/50">
          {node.instruction.text}
        </p>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-slate-700 !border-slate-900" />
    </div>
  );
};

const nodeTypes: NodeTypes = {
  retellNode: RetellNodeUI,
};

export default function RetellFlowEditor() {
  const { id: campaignId, agentId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [originalFlow, setOriginalFlow] = useState<RetellFlow | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  useEffect(() => {
    if (!agentId) return;
    api.get(`/accounts/voice/${agentId}/flow`)
      .then(r => {
        setOriginalFlow(r.data);
        const { nodes: rfNodes, edges: rfEdges } = retellFlowToReactFlow(r.data);
        setNodes(rfNodes);
        setEdges(rfEdges);
      })
      .catch(() => toast.error('Failed to load conversation flow'))
      .finally(() => setLoading(false));
  }, [agentId, toast, setNodes, setEdges]);

  const onConnect = useCallback((params: Connection) => {
    setEdges((eds) => addEdge(params, eds));
  }, [setEdges]);

  const onSave = async () => {
    if (!originalFlow || !agentId) return;
    setSaving(true);
    try {
      const updatedNodes = reactFlowToRetellNodes(nodes, edges, originalFlow.nodes);
      const payload = {
        ...originalFlow,
        nodes: updatedNodes,
      };
      await api.patch(`/accounts/voice/${agentId}/flow`, payload);
      toast.success('Flow published to Retell');
    } catch (err) {
      toast.error('Failed to save flow');
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <div className="h-screen w-screen bg-slate-950 flex items-center justify-center">
      <div className="text-center">
        <div className="h-12 w-12 border-4 border-sky-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
        <p className="text-slate-400 font-medium">Syncing architecture...</p>
      </div>
    </div>
  );

  const selectedNode = nodes.find(n => n.id === selectedNodeId)?.data.retellNode as RetellNode | undefined;

  return (
    <div className="h-screen w-screen bg-slate-950 flex flex-col overflow-hidden">
      <header className="h-16 border-b border-slate-800 bg-slate-900/50 backdrop-blur-xl flex items-center justify-between px-6 z-10">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate(`/campaigns/${campaignId}?tab=sequence`)}
            className="p-2 hover:bg-slate-800 rounded-lg text-slate-400 transition-colors"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h1 className="text-sm font-black uppercase tracking-widest text-white">Retell Flow Editor</h1>
            <p className="text-[10px] text-slate-500 font-bold">AGENT ID: {agentId}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={onSave}
            disabled={saving}
            className="flex items-center gap-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white px-4 py-2 rounded-lg text-xs font-black uppercase tracking-widest transition-all shadow-lg shadow-sky-900/20"
          >
            <Save size={16} />
            {saving ? 'Publishing...' : 'Publish Changes'}
          </button>
        </div>
      </header>

      <div className="flex-1 relative">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => setSelectedNodeId(n.id)}
          onPaneClick={() => setSelectedNodeId(null)}
          fitView
          colorMode="dark"
        >
          <Background color="#1e293b" gap={20} />
          <Controls />
        </ReactFlow>

        {selectedNode && (
          <div className="absolute top-6 right-6 w-80 bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl p-6 z-10 max-h-[calc(100%-48px)] overflow-auto">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-xs font-black uppercase tracking-widest text-white">Node Properties</h3>
              <button onClick={() => setSelectedNodeId(null)} className="text-slate-500 hover:text-white"><X size={18} /></button>
            </div>

            <div className="space-y-6">
              <div>
                <label className="block text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">Node Name</label>
                <input 
                  className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                  value={selectedNode.name}
                  onChange={e => {
                    const val = e.target.value;
                    setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data as any, retellNode: { ...(n.data as any).retellNode, name: val } } } : n));
                  }}
                />
              </div>

              {selectedNode.instruction && (
                <div>
                  <label className="block text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">Instructions</label>
                  <textarea 
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50 min-h-[150px]"
                    value={selectedNode.instruction.text}
                    onChange={e => {
                      const val = e.target.value;
                      setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data as any, retellNode: { ...(n.data as any).retellNode, instruction: { ...(n.data as any).retellNode.instruction, text: val } } } } : n));
                    }}
                  />
                </div>
              )}

              {selectedNode.type === 'transfer_call' && selectedNode.transfer_destination && (
                <div>
                  <label className="block text-[10px] font-black uppercase tracking-widest text-slate-500 mb-2">Transfer Number</label>
                  <input 
                    className="w-full bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                    value={selectedNode.transfer_destination.number}
                    onChange={e => {
                      const val = e.target.value;
                      setNodes(nds => nds.map(n => n.id === selectedNode.id ? { ...n, data: { ...n.data as any, retellNode: { ...(n.data as any).retellNode, transfer_destination: { ...(n.data as any).retellNode.transfer_destination, number: val } } } } : n));
                    }}
                  />
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
