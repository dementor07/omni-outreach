import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Node,
  Edge,
  Connection,
  useNodesState,
  useEdgesState,
  addEdge,
  Background,
  Controls,
  MiniMap,
  Panel,
  Handle,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { api } from '../api/client';
import { useToast } from '../components/Toast';
import { ArrowLeft, X } from 'lucide-react';

interface RetellEdge {
  id: string;
  destination_node_id: string;
  transition_condition?: { type: string; prompt: string };
}

interface RetellNode {
  id: string;
  type: 'conversation' | 'transfer_call' | 'end';
  name: string;
  display_position: { x: number; y: number };
  instruction?: { type: string; text: string };
  edges?: RetellEdge[];
  edge?: RetellEdge;
  transfer_destination?: { type: string; number: string };
  transfer_option?: Record<string, unknown>;
}

interface RetellFlowResponse {
  conversation_flow_id: string;
  global_prompt: string;
  start_node_id: string;
  nodes: RetellNode[];
}

// Custom Node Components
export const ConversationNodeCard = ({ data }: { data: RetellNode }) => (
  <div className="w-64 bg-slate-800 border border-slate-700 rounded-lg p-3 shadow-xl">
    <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-slate-500" />
    <div className="mb-2">
      <h4 className="font-medium text-slate-100 text-sm truncate">{data.name}</h4>
      <p className="text-[10px] text-slate-500 font-bold uppercase tracking-wider">Conversation</p>
    </div>
    <div className="bg-slate-900/50 rounded p-2 border border-slate-700/50">
      <p className="text-xs text-slate-400 line-clamp-2">
        {data.instruction?.text || 'No instructions set'}
      </p>
    </div>
    <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-slate-500" />
  </div>
);

export const TransferCallNodeCard = ({ data }: { data: RetellNode }) => (
  <div className="w-64 bg-indigo-950 border border-indigo-900 rounded-lg p-3 shadow-xl">
    <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-indigo-500" />
    <div className="mb-2">
      <h4 className="font-medium text-slate-100 text-sm truncate">{data.name}</h4>
      <p className="text-[10px] text-indigo-400 font-bold uppercase tracking-wider">Transfer Call</p>
    </div>
    <div className="bg-indigo-900/30 rounded p-2 border border-indigo-800/50">
      <p className="text-xs text-slate-300">
        To: {data.transfer_destination?.number || 'No number'}
      </p>
    </div>
    <Handle type="source" position={Position.Bottom} className="w-2 h-2 !bg-indigo-500" />
  </div>
);

export const EndNodeCard = ({ data }: { data: RetellNode }) => (
  <div className="w-64 bg-rose-950 border border-rose-900 rounded-lg p-3 shadow-xl">
    <Handle type="target" position={Position.Top} className="w-2 h-2 !bg-rose-500" />
    <div className="mb-2">
      <h4 className="font-medium text-slate-100 text-sm truncate">{data.name}</h4>
      <p className="text-[10px] text-rose-400 font-bold uppercase tracking-wider">End Call</p>
    </div>
    <div className="bg-rose-900/30 rounded p-2 border border-rose-800/50">
      <p className="text-xs text-slate-400">End Call</p>
    </div>
  </div>
);

const nodeTypes = {
  conversation: ConversationNodeCard,
  transfer_call: TransferCallNodeCard,
  end: EndNodeCard,
};

export default function RetellFlowEditor() {
  const { campaignId, agentId } = useParams<{ campaignId: string; agentId: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [flowData, setFlowData] = useState<RetellFlowResponse | null>(null);
  const [selectedNode, setSelectedNode] = useState<RetellNode | null>(null);
  const [saving, setSaving] = useState(false);
  const [globalPrompt, setGlobalPrompt] = useState('');
  const [globalPromptSaving, setGlobalPromptSaving] = useState(false);

  const fetchFlow = useCallback(async () => {
    try {
      const resp = await api.get<RetellFlowResponse>(`/accounts/voice/${agentId}/flow`);
      setFlowData(resp.data);
      setGlobalPrompt(resp.data.global_prompt ?? '');

      const rfNodes: Node[] = resp.data.nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.display_position,
        data: { ...n },
      }));

      const rfEdges: Edge[] = [];
      resp.data.nodes.forEach((n) => {
        const outgoing = [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])];
        outgoing.forEach((e) => {
          rfEdges.push({
            id: e.id,
            source: n.id,
            target: e.destination_node_id,
            label: e.transition_condition?.prompt?.slice(0, 40) ?? '',
            type: 'default',
          });
        });
      });

      setNodes(rfNodes);
      setEdges(rfEdges);
    } catch (err) {
      toast.error('Failed to load flow');
    }
  }, [agentId, setNodes, setEdges, toast]);

  useEffect(() => {
    fetchFlow();
  }, [fetchFlow]);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges],
  );

  const onNodeClick = (_: React.MouseEvent, node: Node) => {
    setSelectedNode(node.data as unknown as RetellNode);
  };

  const handleSaveGlobalPrompt = async () => {
    if (!flowData) return;
    setGlobalPromptSaving(true);
    try {
      await api.patch(`/accounts/voice/${agentId}/flow`, {
        global_prompt: globalPrompt,
        nodes: flowData.nodes,
        start_node_id: flowData.start_node_id,
      });
      toast.success('Global prompt saved');
    } catch {
      toast.error('Failed to save global prompt');
    } finally {
      setGlobalPromptSaving(false);
    }
  };

  const handlePublish = async () => {
    if (!flowData) return;
    setSaving(true);
    try {
      // Re-construct the Retell nodes from ReactFlow nodes and edges
      const updatedRetellNodes: RetellNode[] = nodes.map((rn) => {
        const data = rn.data as unknown as RetellNode;
        const nodeEdges = edges.filter((e) => e.source === rn.id);
        
        const retellEdges: RetellEdge[] = nodeEdges.map((e) => {
          // Find if this edge existed in original data to preserve its transition_condition if not edited
          return {
            id: e.id,
            destination_node_id: e.target,
            transition_condition: (data.edges?.find(oe => oe.id === e.id) || data.edge)?.transition_condition ?? { type: 'prompt', prompt: e.label as string || '' }
          };
        });

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

      await api.patch(`/accounts/voice/${agentId}/flow`, {
        ...flowData,
        nodes: updatedRetellNodes,
      });
      toast.success('Published successfully');
    } catch (err) {
      toast.error('Failed to publish');
    } finally {
      setSaving(false);
    }
  };

  const updateSelectedNode = (updates: Partial<RetellNode>) => {
    if (!selectedNode) return;
    const newNodeData = { ...selectedNode, ...updates };
    setSelectedNode(newNodeData);
    setNodes((nds) =>
      nds.map((n) => (n.id === selectedNode.id ? { ...n, data: newNodeData } : n))
    );
  };

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-200">
      <header className="flex items-center justify-between px-4 py-3 border-b border-slate-800 bg-slate-900">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate(-1)}
            className="flex items-center gap-1 text-slate-400 hover:text-slate-200 transition-colors text-sm font-medium"
          >
            <ArrowLeft size={18} /> Back
          </button>
          <div className="h-4 w-px bg-slate-700" />
          <h1 className="text-sm font-bold text-slate-100">Voice Flow Editor</h1>
        </div>
        <button
          onClick={handlePublish}
          disabled={saving}
          className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white text-sm px-4 py-2 rounded-lg font-bold transition-all"
        >
          {saving ? 'Publishing...' : 'Publish to Retell'}
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="flex-1 relative">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            onNodeClick={onNodeClick}
            fitView
            className="bg-slate-950"
          >
            <Background color="#334155" gap={20} />
            <Controls />
            <MiniMap
              nodeColor={(n) => {
                if (n.type === 'end') return '#9f1239';
                if (n.type === 'transfer_call') return '#312e81';
                return '#334155';
              }}
              style={{ backgroundColor: '#020617' }}
            />
            <Panel position="top-right">
              <div className="bg-slate-900 border border-slate-700 rounded-xl p-4 shadow-2xl w-72 flex flex-col gap-3">
                <h4 className="text-[10px] font-black uppercase tracking-widest text-slate-400">Global Prompt</h4>
                <textarea
                  value={globalPrompt}
                  onChange={(e) => setGlobalPrompt(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-sky-500/50 min-h-[120px] resize-none"
                  placeholder="System-level instructions for the entire flow..."
                />
                <button
                  onClick={handleSaveGlobalPrompt}
                  disabled={globalPromptSaving}
                  className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-[10px] font-black uppercase tracking-widest px-4 py-2 rounded-lg transition-all"
                >
                  {globalPromptSaving ? 'Saving...' : 'Save Global Prompt'}
                </button>
              </div>
            </Panel>
          </ReactFlow>
        </div>

        {selectedNode && (
          <aside className="w-80 border-l border-slate-800 bg-slate-900 p-4 overflow-y-auto flex flex-col gap-6 shadow-2xl">
            <div className="flex items-center justify-between">
              <h3 className="font-bold text-slate-100 text-xs uppercase tracking-widest">Node Settings</h3>
              <button onClick={() => setSelectedNode(null)} className="text-slate-500 hover:text-slate-300 transition-colors">
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-1.5 block">Name</label>
                <input
                  value={selectedNode.name}
                  onChange={(e) => updateSelectedNode({ name: e.target.value })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                />
              </div>

              <div>
                <label className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-1.5 block">Instructions</label>
                <textarea
                  value={selectedNode.instruction?.text || ''}
                  onChange={(e) => updateSelectedNode({ instruction: { type: 'text', text: e.target.value } })}
                  className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50 min-h-[120px] resize-none"
                />
              </div>

              {selectedNode.type === 'transfer_call' && (
                <div>
                  <label className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-1.5 block">Phone Number</label>
                  <input
                    value={selectedNode.transfer_destination?.number || ''}
                    onChange={(e) => updateSelectedNode({ transfer_destination: { type: 'number', number: e.target.value } })}
                    className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-sky-500/50"
                  />
                </div>
              )}

              {selectedNode.type === 'conversation' && (
                <div className="space-y-4 pt-4 border-t border-slate-800">
                  <h4 className="text-[10px] font-black uppercase tracking-widest text-slate-500">Outgoing Edges</h4>
                  {(selectedNode.edges || []).map((edge, idx) => (
                    <div key={edge.id} className="p-3 bg-slate-800/50 rounded-lg border border-slate-700/50 space-y-3">
                      <div>
                        <label className="text-[9px] font-bold uppercase text-slate-600 mb-1 block">Condition</label>
                        <textarea
                          value={edge.transition_condition?.prompt || ''}
                          onChange={(e) => {
                            const newEdges = [...(selectedNode.edges || [])];
                            newEdges[idx] = { ...edge, transition_condition: { type: 'prompt', prompt: e.target.value } };
                            updateSelectedNode({ edges: newEdges });
                          }}
                          className="w-full bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:ring-1 focus:ring-sky-500"
                        />
                      </div>
                      <div>
                        <label className="text-[9px] font-bold uppercase text-slate-600 mb-1 block">Destination</label>
                        <select
                          value={edge.destination_node_id}
                          onChange={(e) => {
                            const newEdges = [...(selectedNode.edges || [])];
                            newEdges[idx] = { ...edge, destination_node_id: e.target.value };
                            updateSelectedNode({ edges: newEdges });
                            // Also update ReactFlow edge target
                            setEdges((eds) => eds.map((re) => re.id === edge.id ? { ...re, target: e.target.value } : re));
                          }}
                          className="w-full bg-slate-900 border border-slate-700 rounded-md px-2 py-1.5 text-xs text-slate-300 focus:outline-none"
                        >
                          {flowData?.nodes.map((n) => (
                            <option key={n.id} value={n.id}>{n.name} ({n.id.slice(0, 4)})</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
