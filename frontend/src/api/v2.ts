/**
 * Typed client for the v2 backend (FastAPI, /api/*).
 * Mirrors the Pydantic response models on each router.
 * The HTTP layer is the shared `api` axios instance from ./client.
 */
import { api } from './client'

// ── Shared scalars ───────────────────────────────────────────────────────────
export type UUID = string
export type ISODate = string

// ── Auth ─────────────────────────────────────────────────────────────────────
export interface MeResponse {
  user_id: UUID
  email: string
  workspace_id: UUID | null
}

export const auth = {
  me: () => api.get<MeResponse>('/auth/me').then((r) => r.data),
  login: (email: string, password: string) =>
    api.post<{ access_token: string }>('/auth/login', { email, password }).then((r) => r.data),
}

// ── Workspaces ───────────────────────────────────────────────────────────────
export interface Workspace {
  id: UUID
  name: string
  slug: string
  created_at: ISODate
}

export const workspaces = {
  list: () => api.get<Workspace[]>('/workspaces').then((r) => r.data),
  create: (name: string) => api.post<Workspace>('/workspaces', { name }).then((r) => r.data),
  switch: (id: UUID) => api.post<{ ok: true }>(`/workspaces/${id}/switch`).then((r) => r.data),
}

// ── Nodes (manifest registry) ────────────────────────────────────────────────
export interface NodeHandleManifest {
  name: string
  description: string
}

export interface NodeManifest {
  type: string
  category: string
  summary: string
  config_schema: Record<string, unknown>
  output_handles: NodeHandleManifest[]
  capabilities: string[]
  side_effect: 'READ' | 'NETWORK' | 'MUTATE'
  icon: string
}

export interface NodeExecuteRequest {
  config?: Record<string, unknown>
  lead?: Record<string, unknown>
  workflow_id?: UUID
  node_id?: UUID
  correlation_id?: UUID
}

export interface NodeExecuteResponse {
  handle: string
  telemetry: Record<string, unknown>
  events_published: number
  error: string | null
}

export const nodes = {
  list: () => api.get<NodeManifest[]>('/nodes').then((r) => r.data),
  get: (type: string) => api.get<NodeManifest>(`/nodes/${type}`).then((r) => r.data),
  execute: (type: string, body: NodeExecuteRequest) =>
    api.post<NodeExecuteResponse>(`/nodes/${type}/execute`, body).then((r) => r.data),
}

// ── Canvas (workflows + nodes + edges) ───────────────────────────────────────
export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived'

export interface Workflow {
  id: UUID
  name: string
  status: WorkflowStatus
  timezone: string
  created_at: ISODate
  updated_at: ISODate
}

export interface WorkflowNode {
  id: UUID
  workflow_id: UUID
  node_type: string
  position_x: number
  position_y: number
  config: Record<string, unknown>
}

export interface WorkflowEdge {
  id: UUID
  workflow_id: UUID
  source_node_id: UUID
  target_node_id: UUID
  source_handle: string
  target_handle: string
}

export interface WorkflowDetail {
  workflow: Workflow
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export const canvas = {
  list: () => api.get<Workflow[]>('/canvas/workflows').then((r) => r.data),
  create: (name: string, timezone = 'UTC') =>
    api.post<Workflow>('/canvas/workflows', { name, timezone }).then((r) => r.data),
  get: (id: UUID) => api.get<WorkflowDetail>(`/canvas/workflows/${id}`).then((r) => r.data),
  update: (id: UUID, body: Partial<Pick<Workflow, 'name' | 'status' | 'timezone'>>) =>
    api.patch<Workflow>(`/canvas/workflows/${id}`, body).then((r) => r.data),
  archive: (id: UUID) => api.delete(`/canvas/workflows/${id}`).then(() => undefined),

  addNode: (
    workflowId: UUID,
    body: { node_type: string; position_x?: number; position_y?: number; config?: Record<string, unknown> },
  ) => api.post<WorkflowNode>(`/canvas/workflows/${workflowId}/nodes`, body).then((r) => r.data),
  updateNode: (workflowId: UUID, nodeId: UUID, body: Partial<Pick<WorkflowNode, 'position_x' | 'position_y' | 'config'>>) =>
    api.patch<WorkflowNode>(`/canvas/workflows/${workflowId}/nodes/${nodeId}`, body).then((r) => r.data),
  removeNode: (workflowId: UUID, nodeId: UUID) =>
    api.delete(`/canvas/workflows/${workflowId}/nodes/${nodeId}`).then(() => undefined),

  addEdge: (
    workflowId: UUID,
    body: { source_node_id: UUID; target_node_id: UUID; source_handle?: string; target_handle?: string },
  ) => api.post<WorkflowEdge>(`/canvas/workflows/${workflowId}/edges`, body).then((r) => r.data),
  removeEdge: (workflowId: UUID, edgeId: UUID) =>
    api.delete(`/canvas/workflows/${workflowId}/edges/${edgeId}`).then(() => undefined),

  // Bulk replace the whole graph in one transaction (local-state-first editor).
  saveGraph: (
    workflowId: UUID,
    graph: {
      nodes: Array<{ id: UUID; node_type: string; position_x: number; position_y: number; config: Record<string, unknown> }>
      edges: Array<{ id?: UUID; source_node_id: UUID; target_node_id: UUID; source_handle?: string; target_handle?: string }>
    },
  ) => api.put<WorkflowDetail>(`/canvas/workflows/${workflowId}/graph`, graph).then((r) => r.data),
}

// ── Projections (read-only views) ────────────────────────────────────────────
export interface Contact {
  id: UUID
  email: string | null
  first_name: string | null
  last_name: string | null
  company: string | null
  headline: string | null
  linkedin_url: string | null
  phone: string | null
  source: string | null
  custom_fields: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
}

export interface Company {
  id: UUID
  name: string
  domain: string | null
  industry: string | null
  size: string | null
  custom_fields: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
}

export interface Deal {
  id: UUID
  name: string
  stage: string
  value: string | null // Decimal serialised as string
  currency: string
  contact_id: UUID | null
  company_id: UUID | null
  owner_user_id: UUID | null
  close_date: ISODate | null
  custom_fields: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
}

export interface Lead {
  id: UUID
  contact_id: UUID | null
  workflow_id: UUID | null
  current_node_id: UUID | null
  status: string
  custom_fields: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
}

export const projections = {
  contacts: (limit = 100) => api.get<Contact[]>('/projections/contacts', { params: { limit } }).then((r) => r.data),
  companies: (limit = 100) => api.get<Company[]>('/projections/companies', { params: { limit } }).then((r) => r.data),
  deals: (params: { stage?: string; limit?: number } = {}) =>
    api.get<Deal[]>('/projections/deals', { params }).then((r) => r.data),
  leads: (params: { workflow_id?: UUID; limit?: number } = {}) =>
    api.get<Lead[]>('/projections/leads', { params }).then((r) => r.data),
}

// ── Inbox ────────────────────────────────────────────────────────────────────
export interface InboxThread {
  contact_id: UUID
  last_message_at: ISODate
  message_count: number
  last_classification: string | null
  last_snippet: string | null
  last_channel: string | null
}

export interface InboxMessage {
  id: UUID
  contact_id: UUID | null
  channel: string
  direction: string
  subject: string | null
  body: string | null
  classification: string | null
  confidence: number | null
  metadata: Record<string, unknown>
  occurred_at: ISODate
}

export const inbox = {
  threads: (limit = 50) => api.get<InboxThread[]>('/inbox/threads', { params: { limit } }).then((r) => r.data),
  thread: (contactId: UUID, limit = 200) =>
    api.get<InboxMessage[]>(`/inbox/threads/${contactId}`, { params: { limit } }).then((r) => r.data),
}

// ── Integrations (connections) ───────────────────────────────────────────────
export interface Connection {
  id: UUID
  provider: string
  name: string
  metadata: Record<string, unknown>
  connected_at: ISODate
  last_refreshed_at: ISODate | null
}

export interface ConnectionCreate {
  provider: string
  name: string
  credentials: Record<string, unknown>
  metadata?: Record<string, unknown>
}

export const integrations = {
  list: (provider?: string) =>
    api.get<Connection[]>('/integrations', { params: provider ? { provider } : undefined }).then((r) => r.data),
  create: (body: ConnectionCreate) => api.post<Connection>('/integrations', body).then((r) => r.data),
  remove: (id: UUID) => api.delete(`/integrations/${id}`).then(() => undefined),
}

// ── Events ───────────────────────────────────────────────────────────────────
export interface OmniEvent {
  id: UUID
  workspace_id: UUID
  event_type: string
  entity_type: string
  entity_id: UUID | null
  payload: Record<string, unknown>
  actor_user_id: UUID | null
  correlation_id: UUID | null
  occurred_at: ISODate
}

export interface EventQuery {
  entity_type?: string
  entity_id?: UUID
  event_type?: string
  correlation_id?: UUID
  since?: ISODate
  until?: ISODate
  limit?: number
}

export const events = {
  list: (params: EventQuery = {}) => api.get<OmniEvent[]>('/events', { params }).then((r) => r.data),
  publish: (body: {
    event_type: string
    entity_type: string
    entity_id?: UUID
    payload?: Record<string, unknown>
    correlation_id?: UUID
  }) => api.post<OmniEvent>('/events', body).then((r) => r.data),
}

// ── AI (scores + AI Studio jobs) ─────────────────────────────────────────────
export type LeadTier = 'hot' | 'warm' | 'cold'

export interface LeadScore {
  lead_id: UUID
  contact_id: UUID | null
  score: number
  tier: LeadTier
  reasons: string[]
  model: string | null
  scored_at: ISODate
}

export type AiJobKind = 'score' | 'compose' | 'enrich' | 'classify'
export type AiJobStatus = 'queued' | 'running' | 'done' | 'failed'

export interface AiJob {
  id: UUID
  kind: AiJobKind
  status: AiJobStatus
  entity_type: string | null
  entity_id: UUID | null
  input: Record<string, unknown>
  output: Record<string, unknown>
  model: string | null
  cost_usd: string | null
  error: string | null
  created_at: ISODate
  completed_at: ISODate | null
}

export interface AiJobCreate {
  kind: AiJobKind
  entity_type?: string
  entity_id?: UUID
  config?: Record<string, unknown>
  lead?: Record<string, unknown>
}

export const ai = {
  scores: (params: { tier?: LeadTier; limit?: number } = {}) =>
    api.get<LeadScore[]>('/ai/scores', { params }).then((r) => r.data),
  score: (leadId: UUID) => api.get<LeadScore>(`/ai/scores/${leadId}`).then((r) => r.data),
  jobs: (params: { kind?: AiJobKind; status?: AiJobStatus; limit?: number } = {}) =>
    api.get<AiJob[]>('/ai/jobs', { params }).then((r) => r.data),
  runJob: (body: AiJobCreate) =>
    api.post<{ job_id: UUID; kind: string; status: string; correlation_id: UUID }>('/ai/jobs', body).then((r) => r.data),
}
