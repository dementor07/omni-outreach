You are an expert React/TypeScript and FastAPI engineer implementing a feature.

# SPEC: Retell Voice Node Editor — Round 3

---

## 1. OBJECTIVE

Implement the Retell voice node editor: Standard mode adds `begin_message` + `general_prompt` editing to the existing ConfigSidebar; Nested Flow mode adds a new full-screen ReactFlow sub-canvas at `/campaigns/:id/voice-flow/:agentId` where Retell conversation flow nodes are editable and publishable back to the Retell API.

---

## 2. FILES TO CHANGE

| File | Action |
|------|--------|
| `backend/app/routers/accounts.py` | Add 4 new endpoints (see §4.1) |
| `frontend/src/pages/Campaigns.tsx` | Update ConfigSidebar voice section only (see §4.2) |
| `frontend/src/pages/RetellFlowEditor.tsx` | CREATE new file (see §4.3) |
| `frontend/src/App.tsx` | Add one route inside `<RequireAuth>` (see §4.4) |

---

## 3. DO NOT TOUCH

- `backend/app/routers/sequencer.py`
- `backend/app/routers/dispatcher.py`
- `frontend/src/pages/SequentialBuilder.tsx`
- Any node type in `Campaigns.tsx` that is not the `voice` node
- The `ActionNode` card render logic in `Campaigns.tsx`
- The `CustomEdge` component in `Campaigns.tsx` — reuse it, don't rewrite it
- `frontend/src/components/Sidebar.tsx` — do NOT add nav items (RetellFlowEditor is not a top-level page)
- Any existing campaign or account routes not listed in §2

---

## 4. IMPLEMENTATION

### 4.1 Backend — `backend/app/routers/accounts.py`

Add these four endpoints. All Retell API calls use the `RETELL_API_KEY` env var as `Authorization: Bearer {key}`. Use `httpx.AsyncClient` (already used in this file).

---

#### `GET /accounts/voice/{agent_id}/prompt`

```python
@router.get("/voice/{agent_id}/prompt")
async def get_voice_agent_prompt(agent_id: int, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` table: `SELECT retell_agent_id FROM voice_agents WHERE id = $1` → get `retell_agent_id`
2. `GET https://api.retellai.com/get-agent/{retell_agent_id}` → parse `response_engine`
3. Assert `response_engine.type == "retell-llm"`, extract `llm_id`
4. `GET https://api.retellai.com/get-retell-llm/{llm_id}` → return `{ llm_id, begin_message, general_prompt, model }`

Return type:
```python
class VoiceAgentPrompt(BaseModel):
    llm_id: str
    begin_message: str
    general_prompt: str
    model: str
```

---

#### `PATCH /accounts/voice/{agent_id}/prompt`

```python
@router.patch("/voice/{agent_id}/prompt")
async def update_voice_agent_prompt(agent_id: int, body: UpdatePromptRequest, db=Depends(get_db)):
```

Request body:
```python
class UpdatePromptRequest(BaseModel):
    begin_message: str
    general_prompt: str
```

Steps:
1. Query `voice_agents` for `retell_agent_id`
2. `GET https://api.retellai.com/get-agent/{retell_agent_id}` → extract `llm_id`
3. `PATCH https://api.retellai.com/update-retell-llm/{llm_id}` with `{ begin_message, general_prompt }`
4. Return `{ success: true }`

---

#### `GET /accounts/voice/{agent_id}/flow`

```python
@router.get("/voice/{agent_id}/flow")
async def get_voice_agent_flow(agent_id: int, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` for `retell_agent_id`
2. `GET https://api.retellai.com/get-agent/{retell_agent_id}` → extract `conversation_flow_id` from `response_engine`
3. `GET https://api.retellai.com/get-conversation-flow/{conversation_flow_id}` → return full JSON as-is

---

#### `PATCH /accounts/voice/{agent_id}/flow`

```python
@router.patch("/voice/{agent_id}/flow")
async def update_voice_agent_flow(agent_id: int, body: dict, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` for `retell_agent_id`
2. `GET https://api.retellai.com/get-agent/{retell_agent_id}` → extract `conversation_flow_id`
3. `PATCH https://api.retellai.com/update-conversation-flow/{conversation_flow_id}` with `body` as JSON
4. Return `{ success: true }`

---

### 4.2 Frontend — `frontend/src/pages/Campaigns.tsx`

**Locate the ConfigSidebar section that renders when `selectedNode.type === 'voice'`.**

Do not touch anything outside that block.

---

#### Standard Mode additions

When `operationMode === 'standard'` and `selectedVoiceAgentId` is set, render below the agent dropdown:

```tsx
// State (add near top of ConfigSidebar or as local state):
const [agentPrompt, setAgentPrompt] = useState<{ begin_message: string; general_prompt: string } | null>(null);
const [promptLoading, setPromptLoading] = useState(false);
const [promptSaving, setPromptSaving] = useState(false);
```

Use a `useEffect` that fires when `selectedVoiceAgentId` changes and `operationMode === 'standard'`:
```ts
// GET /accounts/voice/{selectedVoiceAgentId}/prompt via `api` client
// Set agentPrompt state on success
// Use toast.error() on failure
```

Render (only when `agentPrompt` is not null):
```tsx
<div className="mt-4 space-y-3">
  <div>
    <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">Begin Message</label>
    <input
      className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500"
      value={agentPrompt.begin_message}
      onChange={e => setAgentPrompt(p => p ? { ...p, begin_message: e.target.value } : p)}
    />
  </div>
  <div>
    <label className="text-xs font-medium text-slate-400 uppercase tracking-wide">System Prompt</label>
    <textarea
      className="mt-1 w-full bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-sky-500 resize-y"
      style={{ minHeight: 200 }}
      value={agentPrompt.general_prompt}
      onChange={e => setAgentPrompt(p => p ? { ...p, general_prompt: e.target.value } : p)}
    />
  </div>
  <button
    disabled={promptSaving}
    onClick={handleSavePrompt}
    className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-lg transition-colors"
  >
    {promptSaving ? 'Saving…' : 'Save Prompt'}
  </button>
</div>
```

`handleSavePrompt`:
```ts
// PATCH /accounts/voice/{selectedVoiceAgentId}/prompt
// On success: toast.success('Prompt saved')
// On error: toast.error('Failed to save prompt')
```

---

#### Nested Flow Mode additions

When `operationMode === 'flow'` and `selectedVoiceAgentId` is set, replace (or add below) the existing flow dropdown with:

```tsx
// State:
const [flowMeta, setFlowMeta] = useState<{ node_count: number; edge_count: number } | null>(null);
```

Use a `useEffect` that fires when `selectedVoiceAgentId` changes and `operationMode === 'flow'`:
```ts
// GET /accounts/voice/{selectedVoiceAgentId}/flow
// Compute node_count = flow.nodes.length
// Compute edge_count = sum of edges arrays across all nodes
// Set flowMeta
```

Render:
```tsx
<div className="mt-4 space-y-2">
  <button
    onClick={() => navigate(`/campaigns/${campaignId}/voice-flow/${selectedVoiceAgentId}`)}
    className="w-full flex items-center justify-between bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium px-4 py-2.5 rounded-lg transition-colors"
  >
    <span>Open Flow Editor</span>
    <span>→</span>
  </button>
  {flowMeta && (
    <p className="text-xs text-slate-500 text-center">
      {flowMeta.node_count} nodes · {flowMeta.edge_count} edges
    </p>
  )}
</div>
```

To get `campaignId` inside ConfigSidebar: extract it from `useParams()` or pass it as a prop from the parent — use whichever pattern already exists in Campaigns.tsx. Use `useNavigate()` for navigation.

---

### 4.3 Frontend — `frontend/src/pages/RetellFlowEditor.tsx` (NEW FILE)

**Full file structure:**

```tsx
import { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactFlow, {
  Background, Controls, MiniMap,
  addEdge, useNodesState, useEdgesState,
  Node, Edge, Connection, NodeTypes
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import api from '../api/client';
import { useToast } from '../components/Toast';
```

#### Types

```ts
interface RetellEdge {
  id: string;
  destination_node_id: string;
  transition_condition: { type: string; prompt: string };
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
  transfer_option?: { type: string; enable_bridge_audio_cue: boolean };
}

interface RetellFlow {
  conversation_flow_id: string;
  global_prompt: string;
  start_node_id: string;
  nodes: RetellNode[];
}
```

#### Conversion helpers

```ts
function retellNodesToFlow(nodes: RetellNode[]): Node[] {
  return nodes.map(n => ({
    id: n.id,
    type: n.type,  // matches custom node type keys
    position: { x: n.display_position.x, y: n.display_position.y },
    data: { ...n }
  }));
}

function retellEdgesToFlow(nodes: RetellNode[]): Edge[] {
  // For each node, iterate n.edges (array) or n.edge (single) and create Edge objects
  // label = transition_condition.prompt truncated to 40 chars
  // id = retell edge id
  // source = node.id, target = edge.destination_node_id
}

function flowToRetellNodes(rfNodes: Node[], rfEdges: Edge[]): RetellNode[] {
  // Reconstruct RetellNode[] from ReactFlow nodes + edges
  // Preserve display_position from node.position
  // Re-attach edges/edge arrays from rfEdges filtered by source
}
```

#### Custom node components

```tsx
function ConversationNode({ data }: { data: RetellNode }) {
  return (
    <div className="bg-slate-700 border border-slate-500 rounded-xl px-4 py-3 w-56 shadow-lg">
      <p className="text-xs font-semibold text-sky-400 uppercase tracking-wide mb-1">{data.name}</p>
      <p className="text-xs text-slate-300 line-clamp-2">{data.instruction?.text?.slice(0, 60)}</p>
    </div>
  );
}

function TransferCallNode({ data }: { data: RetellNode }) {
  return (
    <div className="bg-indigo-900 border border-indigo-500 rounded-xl px-4 py-3 w-56 shadow-lg">
      <p className="text-xs font-semibold text-indigo-300 uppercase tracking-wide mb-1">{data.name}</p>
      <p className="text-xs text-slate-300">{data.transfer_destination?.number}</p>
    </div>
  );
}

function EndNode({ data }: { data: RetellNode }) {
  return (
    <div className="bg-rose-900 border border-rose-500 rounded-xl px-4 py-3 w-48 shadow-lg">
      <p className="text-xs font-semibold text-rose-300 uppercase tracking-wide">{data.name}</p>
    </div>
  );
}

const nodeTypes: NodeTypes = {
  conversation: ConversationNode,
  transfer_call: TransferCallNode,
  end: EndNode,
};
```

#### Config panel component

```tsx
function NodeConfigPanel({
  node,
  allNodes,
  onChange,
  onClose
}: {
  node: Node;
  allNodes: Node[];
  onChange: (updated: Node) => void;
  onClose: () => void;
}) {
  // Renders right-side panel (fixed, w-80, right-0, top-0, h-full, bg-slate-800)
  // conversation: name input, instruction textarea, list of outgoing edges (condition + destination select)
  // transfer_call: name input, phone number input, instruction textarea
  // end: name input, instruction textarea
  // All changes call onChange(updatedNode) immediately (controlled)
  // "×" button calls onClose
}
```

#### Main page component

```tsx
export default function RetellFlowEditor() {
  const { campaignId, agentId } = useParams<{ campaignId: string; agentId: string }>();
  const navigate = useNavigate();
  const toast = useToast();

  const [flow, setFlow] = useState<RetellFlow | null>(null);
  const [globalPrompt, setGlobalPrompt] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
```

**Load on mount:**
```ts
useEffect(() => {
  api.get(`/accounts/voice/${agentId}/flow`)
    .then(res => {
      setFlow(res.data);
      setGlobalPrompt(res.

[... truncated 6519 chars ...]

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.