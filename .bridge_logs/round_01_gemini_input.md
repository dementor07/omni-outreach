You are an expert React/TypeScript and FastAPI engineer implementing a feature.

# SPEC: Retell Voice Node Editor

---

## 1. OBJECTIVE

Extend the Omni voice node so Standard mode edits `begin_message` + `general_prompt` live via Retell API, and Nested Flow mode opens a full ReactFlow sub-canvas at `/campaigns/:id/voice-flow/:agentId` where conversation flow nodes are editable and publishable back to Retell.

---

## 2. FILES TO CHANGE

```
backend/app/routers/accounts.py          ← add 4 new endpoints
frontend/src/pages/Campaigns.tsx         ← update voice ConfigSidebar section only
frontend/src/pages/RetellFlowEditor.tsx  ← NEW file
frontend/src/App.tsx                     ← add one route inside RequireAuth
```

---

## 3. DO NOT TOUCH

**CRITICAL — Gemini must not modify these:**

- `backend/app/services/sequencer.py`
- `backend/app/services/dispatcher.py`
- `frontend/src/pages/SequentialBuilder.tsx`
- Any non-voice section of `frontend/src/pages/Campaigns.tsx` — do not rewrite ActionNode, CanvasArea, edge logic, or any node type other than the voice ConfigSidebar section
- `frontend/src/components/Sidebar.tsx` — do NOT add a nav item (this is not a top-level page)
- `frontend/src/api/client.ts`
- Any existing database migrations or schema files

---

## 4. IMPLEMENTATION

### 4.1 Backend — `backend/app/routers/accounts.py`

Add the following four endpoints. Do not rewrite or reorder existing endpoints.

#### Endpoint 1: `GET /accounts/voice/{agent_id}/prompt`

```python
@router.get("/voice/{agent_id}/prompt")
async def get_voice_agent_prompt(agent_id: int, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` table for row where `id = agent_id`, get `retell_agent_id`
2. Call `GET https://api.retellai.com/get-agent/{retell_agent_id}` with `Authorization: Bearer {RETELL_API_KEY}` header
3. From response, extract `response_engine`. Assert `response_engine.type == "retell-llm"` — raise HTTP 400 with message `"Agent is not a retell-llm type"` if not
4. Extract `llm_id = response_engine.llm_id`
5. Call `GET https://api.retellai.com/get-retell-llm/{llm_id}`
6. Return: `{ "begin_message": ..., "general_prompt": ..., "llm_id": ..., "model": ... }`

#### Endpoint 2: `PATCH /accounts/voice/{agent_id}/prompt`

```python
class UpdatePromptRequest(BaseModel):
    begin_message: str
    general_prompt: str

@router.patch("/voice/{agent_id}/prompt")
async def update_voice_agent_prompt(agent_id: int, body: UpdatePromptRequest, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` for `retell_agent_id`
2. Call `GET https://api.retellai.com/get-agent/{retell_agent_id}` → extract `llm_id`
3. Call `PATCH https://api.retellai.com/update-retell-llm/{llm_id}` with body `{ "begin_message": body.begin_message, "general_prompt": body.general_prompt }`
4. Return `{ "ok": True }`

#### Endpoint 3: `GET /accounts/voice/{agent_id}/flow`

```python
@router.get("/voice/{agent_id}/flow")
async def get_voice_agent_flow(agent_id: int, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` for `retell_agent_id`
2. Call `GET https://api.retellai.com/get-agent/{retell_agent_id}` → extract `response_engine`
3. Assert `response_engine.type == "conversation-flow"` — raise HTTP 400 `"Agent is not a conversation-flow type"` if not
4. Extract `conversation_flow_id = response_engine.conversation_flow_id`
5. Call `GET https://api.retellai.com/get-conversation-flow/{conversation_flow_id}`
6. Return the full response JSON as-is

#### Endpoint 4: `PATCH /accounts/voice/{agent_id}/flow`

```python
@router.patch("/voice/{agent_id}/flow")
async def update_voice_agent_flow(agent_id: int, body: dict, db=Depends(get_db)):
```

Steps:
1. Query `voice_agents` for `retell_agent_id`
2. `GET /get-agent/{retell_agent_id}` → extract `conversation_flow_id`
3. `PATCH https://api.retellai.com/update-conversation-flow/{conversation_flow_id}` with `body` as JSON payload
4. Return `{ "ok": True }`

**HTTP client**: Use `httpx.AsyncClient` (already used in accounts.py). Read `RETELL_API_KEY` from `os.environ`.

---

### 4.2 Frontend — `frontend/src/pages/Campaigns.tsx` (voice section only)

**Find the voice node's section inside `ConfigSidebar`** — specifically where `selectedNode.type === 'voice'` or equivalent. Replace/extend only this block.

#### Types to add (at top of file, with existing interfaces):

```typescript
interface RetellPrompt {
  begin_message: string;
  general_prompt: string;
  llm_id: string;
  model: string;
}
```

#### State to add inside `ConfigSidebar` (or wherever voice config state lives):

```typescript
const [retellPrompt, setRetellPrompt] = useState<RetellPrompt | null>(null);
const [promptLoading, setPromptLoading] = useState(false);
const [promptSaving, setPromptSaving] = useState(false);
const [flowMeta, setFlowMeta] = useState<{ nodeCount: number; edgeCount: number } | null>(null);
```

#### When `mode === 'standard'` and `selectedVoiceAgentId` changes:

```typescript
useEffect(() => {
  if (mode !== 'standard' || !selectedVoiceAgentId) return;
  setPromptLoading(true);
  api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
    .then(r => setRetellPrompt(r.data))
    .catch(() => toast.error('Failed to load agent prompt'))
    .finally(() => setPromptLoading(false));
}, [selectedVoiceAgentId, mode]);
```

#### Standard mode JSX (below the voice agent dropdown):

```tsx
{mode === 'standard' && selectedVoiceAgentId && (
  <div className="space-y-3 mt-4">
    {promptLoading ? (
      <p className="text-slate-400 text-sm">Loading prompt...</p>
    ) : retellPrompt ? (
      <>
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">Begin Message</label>
          <input
            className="w-full bg-slate-800 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
            value={retellPrompt.begin_message}
            onChange={e => setRetellPrompt(p => p ? { ...p, begin_message: e.target.value } : p)}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">System Prompt</label>
          <textarea
            className="w-full bg-slate-800 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500 resize-y"
            style={{ minHeight: '200px' }}
            value={retellPrompt.general_prompt}
            onChange={e => setRetellPrompt(p => p ? { ...p, general_prompt: e.target.value } : p)}
          />
        </div>
        <button
          disabled={promptSaving}
          onClick={async () => {
            if (!retellPrompt) return;
            setPromptSaving(true);
            try {
              await api.patch(`/accounts/voice/${selectedVoiceAgentId}/prompt`, {
                begin_message: retellPrompt.begin_message,
                general_prompt: retellPrompt.general_prompt,
              });
              toast.success('Prompt saved');
            } catch {
              toast.error('Failed to save prompt');
            } finally {
              setPromptSaving(false);
            }
          }}
          className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-medium py-2 rounded-md transition-colors"
        >
          {promptSaving ? 'Saving...' : 'Save Prompt'}
        </button>
      </>
    ) : null}
  </div>
)}
```

#### When `mode === 'flow'` and `selectedVoiceAgentId` changes:

```typescript
useEffect(() => {
  if (mode !== 'flow' || !selectedVoiceAgentId) return;
  api.get(`/accounts/voice/${selectedVoiceAgentId}/flow`)
    .then(r => {
      const nodes = r.data.nodes ?? [];
      const edges = nodes.flatMap((n: any) => [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])]);
      setFlowMeta({ nodeCount: nodes.length, edgeCount: edges.length });
    })
    .catch(() => setFlowMeta(null));
}, [selectedVoiceAgentId, mode]);
```

#### Flow mode JSX (replace existing flow dropdown with this):

```tsx
{mode === 'flow' && selectedVoiceAgentId && (
  <div className="mt-4 space-y-3">
    <button
      onClick={() => navigate(`/campaigns/${campaignId}/voice-flow/${selectedVoiceAgentId}`)}
      className="w-full flex items-center justify-between bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 transition-colors"
    >
      <span>Open Flow Editor</span>
      <span className="text-slate-400">→</span>
    </button>
    {flowMeta && (
      <p className="text-xs text-slate-500 text-center">
        {flowMeta.nodeCount} nodes · {flowMeta.edgeCount} edges
      </p>
    )}
  </div>
)}
```

Use `useNavigate` from `react-router-dom` (already imported). `campaignId` comes from `useParams` (already used in Campaigns.tsx).

---

### 4.3 Frontend — `frontend/src/pages/RetellFlowEditor.tsx` (NEW FILE)

Default export. Full-screen ReactFlow canvas.

#### Imports:

```typescript
import { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactFlow, {
  Node, Edge, addEdge, useNodesState, useEdgesState,
  Background, Controls, Connection, NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import api from '../api/client';
import { useToast } from '../components/Toast';
```

#### Types:

```typescript
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

interface NodeConfigPanelProps {
  node: RetellNode;
  allNodes: RetellNode[];
  onChange: (updated: RetellNode) => void;
  onClose: () => void;
}
```

#### Helper — `retellFlowToReactFlow(flow: RetellFlow): { nodes: Node[], edges: Edge[] }`:

```typescript
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
```

#### Helper — `reactFlowToRetellNodes(rfNodes: Node[], rfEdges: Edge[], originalNodes: RetellNode[]): RetellNode[]`:

Rebuild the `nodes` array for the PATCH payload:

```typescript
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
      

[... truncated 13581 chars ...]

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.