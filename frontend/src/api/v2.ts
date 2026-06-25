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
// FE-003: matches the real GET /auth/me response (see backend auth.py:me).
// The old shape ({ user_id, workspace_id }) never matched what the server sent.
export interface MeWorkspace {
  id: UUID
  name: string
  slug: string
  role: string
  owner_user_id: UUID
  joined_at: ISODate
}

export interface MeResponse {
  id: UUID
  email: string
  google_connected: boolean
  workspaces: MeWorkspace[]
}

export const auth = {
  me: () => api.get<MeResponse>('/auth/me').then((r) => r.data),
  login: (email: string, password: string) =>
    api.post<{ access_token: string }>('/auth/login', { email, password }).then((r) => r.data),
  changePassword: (currentPassword: string, newPassword: string) =>
    api
      .post<void>('/auth/change-password', { current_password: currentPassword, new_password: newPassword })
      .then(() => undefined),
}

// ── Workspaces ───────────────────────────────────────────────────────────────
export interface Workspace {
  id: UUID
  name: string
  slug: string
  created_at: ISODate
}

export interface WorkspaceMember {
  user_id: UUID
  email: string
  role: string
}

// ── Suppression list (DNC) ────────────────────────────────────────────────────
export type SuppressionKind = 'email' | 'domain' | 'phone' | 'linkedin'

export interface SuppressionRule {
  id: UUID
  kind: SuppressionKind
  value: string
  reason: string | null
  source: string
  created_at: ISODate
}

export const suppression = {
  list: () => api.get<SuppressionRule[]>('/suppression').then((r) => r.data),
  create: (kind: SuppressionKind, value: string, reason?: string) =>
    api.post<SuppressionRule>('/suppression', { kind, value, reason }).then((r) => r.data),
  remove: (id: UUID) => api.delete<void>(`/suppression/${id}`).then(() => undefined),
}

// ── Deliverability evidence ──────────────────────────────────────────────────
export type EmailVerificationStatus = 'verified' | 'valid_domain' | 'risky' | 'invalid' | 'unknown'

export interface EmailVerification {
  email_normalized: string
  status: EmailVerificationStatus
  reason: string
  provider: string
  mx_domain: string | null
  mx_hosts: string[]
  disposable: boolean
  role_based: boolean
  checked_at: ISODate
  expires_at: ISODate
}

export interface DeliverabilitySummary {
  total: number
  verified: number
  valid_domain: number
  risky: number
  invalid: number
  unknown: number
  expired: number
}

export interface VerificationProviderHealth {
  connection_id: UUID
  connection_name: string
  provider: string
  priority: number
  success_count: number
  failure_count: number
  consecutive_failures: number
  last_status: string | null
  last_error_code: string | null
  last_latency_ms: number | null
  last_checked_at: ISODate | null
  open_until: ISODate | null
}

export interface SenderHealth {
  sending_account_id: UUID
  identity: string
  provider: string
  account_status: string
  sent_7d: number
  transient_failures_7d: number
  permanent_failures_7d: number
  health_status: 'healthy' | 'warning' | 'critical' | 'unknown'
  last_event_at: ISODate | null
}

export const deliverability = {
  list: (limit = 100) =>
    api.get<EmailVerification[]>('/deliverability/verifications', { params: { limit } }).then((r) => r.data),
  summary: () => api.get<DeliverabilitySummary>('/deliverability/summary').then((r) => r.data),
  providers: () => api.get<VerificationProviderHealth[]>('/deliverability/providers').then((r) => r.data),
  senderHealth: () => api.get<SenderHealth[]>('/deliverability/sender-health').then((r) => r.data),
  verify: (email: string) =>
    api.post<EmailVerification>('/deliverability/verify', { email }).then((r) => r.data),
}

// ── Templates (shared message library, B5) ────────────────────────────────────
export type TemplateChannel = 'email' | 'linkedin' | 'sms' | 'whatsapp' | 'instagram' | 'telegram' | 'voice'

export interface MessageTemplate {
  id: UUID
  name: string
  channel: TemplateChannel
  category: string | null
  subject: string | null
  body: string
  created_at: ISODate
  updated_at: ISODate
}

export interface TemplateInput {
  name: string
  channel: TemplateChannel
  category?: string | null
  subject?: string | null
  body: string
}

export const templates = {
  list: () => api.get<MessageTemplate[]>('/templates').then((r) => r.data),
  create: (input: TemplateInput) => api.post<MessageTemplate>('/templates', input).then((r) => r.data),
  update: (id: UUID, input: Partial<TemplateInput>) =>
    api.patch<MessageTemplate>(`/templates/${id}`, input).then((r) => r.data),
  remove: (id: UUID) => api.delete<void>(`/templates/${id}`).then(() => undefined),
}

// ── Campaign objectives (the goal a workflow pursues) ─────────────────────────
// Mirrors backend/app/routers/objectives.py. One objective per workflow; the
// objective_controller widens the audience + re-runs until reached or the
// bounds envelope is spent.
// Only metrics the engine can honestly measure from a campaign's own lineage
// (mirrors objective_controller.MEASURABLE_METRICS). No meetings_booked yet —
// no campaign-scoped calendar/deal signal exists, so offering it would be a lie.
export type ObjectiveMetric = 'contacts' | 'qualified_leads' | 'companies' | 'replies'
export type ObjectiveStatus = 'pursuing' | 'reached' | 'exhausted' | 'paused'

export interface ObjectiveAudience {
  keywords?: string[]
  location?: string
  titles?: string[]
  [k: string]: unknown
}

export interface ObjectiveBounds {
  max_iterations?: number
  max_spend_usd?: number
  deadline?: string
  [k: string]: unknown
}

/** Live pursuit telemetry the controller writes back on each run completion. */
export interface ObjectiveProgress {
  current?: number
  iterations_used?: number
  spend_usd?: number
  last_action?: string
  last_evaluated_at?: ISODate
  [k: string]: unknown
}

export interface ObjectiveInput {
  metric: ObjectiveMetric
  target: number
  audience: ObjectiveAudience
  bounds: ObjectiveBounds
}

export interface Objective {
  id: UUID
  workflow_id: UUID
  metric: ObjectiveMetric
  target: number
  audience: ObjectiveAudience
  bounds: ObjectiveBounds
  progress: ObjectiveProgress
  status: ObjectiveStatus
  created_at: ISODate
  updated_at: ISODate
}

export const objectives = {
  get: (workflowId: UUID) =>
    api.get<Objective | null>(`/objectives/${workflowId}`).then((r) => r.data),
  set: (workflowId: UUID, input: ObjectiveInput) =>
    api.put<Objective>(`/objectives/${workflowId}`, input).then((r) => r.data),
  clear: (workflowId: UUID) =>
    api.delete<void>(`/objectives/${workflowId}`).then(() => undefined),
  togglePause: (workflowId: UUID) =>
    api.post<Objective>(`/objectives/${workflowId}/pause`).then((r) => r.data),
}

// ── Analytics (lead-gen efficiency + cost rollup) ─────────────────────────────
export interface AnalyticsSummary {
  runs: number
  companies_collected: number
  companies_qualified: number
  companies_rejected: number
  people_found: number
  people_verified: number
  leads_created: number
  serper_calls: number
  claude_calls: number
  claude_input_tokens: number
  claude_output_tokens: number
  total_cost: number
  email_opens: number
  email_clicks: number
  last_run_at: ISODate | null
}

export type WorkspaceRole = 'owner' | 'admin' | 'member'

export interface WorkspaceInvite {
  id: UUID
  email: string
  role: WorkspaceRole
  token: string
  expires_at: string
  created_at?: string
}

export const workspaces = {
  list: () => api.get<Workspace[]>('/workspaces').then((r) => r.data),
  create: (name: string) => api.post<Workspace>('/workspaces', { name }).then((r) => r.data),
  switch: (id: UUID) =>
    api
      .post<{ workspace_id: UUID; access_token: string; token_type: string }>(`/workspaces/${id}/switch`)
      .then((r) => r.data),
  rename: (id: UUID, name: string) =>
    api.patch<Workspace>(`/workspaces/${id}`, { name }).then((r) => r.data),
  members: (id: UUID) => api.get<WorkspaceMember[]>(`/workspaces/${id}/members`).then((r) => r.data),
  removeMember: (id: UUID, userId: UUID) =>
    api.delete(`/workspaces/${id}/members/${userId}`).then((r) => r.data),
  leave: (id: UUID) => api.post(`/workspaces/${id}/leave`).then((r) => r.data),
  invites: (id: UUID) => api.get<WorkspaceInvite[]>(`/workspaces/${id}/invites`).then((r) => r.data),
  createInvite: (id: UUID, email: string, role: 'admin' | 'member') =>
    api.post<WorkspaceInvite>(`/workspaces/${id}/invites`, { email, role }).then((r) => r.data),
  revokeInvite: (id: UUID, inviteId: UUID) =>
    api.delete(`/workspaces/${id}/invites/${inviteId}`).then((r) => r.data),
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
  side_effect: 'read' | 'network' | 'mutate'
  icon: string
  display_name: string
  primary_fields: string[]
  advanced_fields: string[]
  visible_in_palette: boolean
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

// ── Lead-source preview (synchronous Naukri scrape) ──────────────────────────
export interface NaukriPreviewRequest {
  keyword: string
  location?: string | null
  max_pages?: number
}

export interface NaukriPreviewCompany {
  company_name: string
  title: string
  role_count: number
  location: string
  experience: string
  source_url: string
}

export interface NaukriPreviewResponse {
  keyword: string
  jobs_returned: number
  companies_extracted: number
  companies: NaukriPreviewCompany[]
}

export const sources = {
  naukriPreview: (body: NaukriPreviewRequest) =>
    api.post<NaukriPreviewResponse>('/sources/naukri/preview', body).then((r) => r.data),
}

// ── Canvas (workflows + nodes + edges) ───────────────────────────────────────
export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived'

export interface Workflow {
  id: UUID
  name: string
  status: WorkflowStatus
  timezone: string
  start_at: ISODate | null
  end_at: ISODate | null
  daily_cap: number | null
  earliest_hour: number | null
  latest_hour: number | null
  days_of_week: number[] | null
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

export interface GraphIssue {
  code: string
  message: string
  severity: 'error' | 'warning'
  scope: 'structural' | 'config'
  node_id: UUID | null
  edge_id: UUID | null
}

export interface GraphValidation {
  valid_for_save: boolean
  valid_for_run: boolean
  issues: GraphIssue[]
  error_count: number
  warning_count: number
}

export interface RunResponse {
  lead_id: UUID
  workflow_id: UUID
  start_node_id: UUID
  node_type: string
  correlation_id: UUID
  handle: string
  events_published: number
  sources_started: number
  sources_failed: number
  failures: string[]
  lead_ids: UUID[]
  start_node_ids: UUID[]
  node_types: string[]
}

export interface CampaignTemplateInfo {
  id: string
  name: string
  summary: string
}

export interface GoalWorkflowCreate {
  name: string
  timezone?: string
  metric: ObjectiveMetric
  target: number
  audience: ObjectiveAudience
  bounds: ObjectiveBounds
  template_id?: string | null
}

export type CampaignSourceProvider = 'naukri' | 'searxng' | 'serper_search'
export type PeopleDiscoveryProvider = 'searxng_people' | 'serper_people'
export type EnrichmentProvider = 'apollo' | 'proxycurl' | 'hunter'
export type MessageChannel = 'email' | 'linkedin'

export interface CampaignSourceSpec {
  provider: CampaignSourceProvider
  query?: string | null
  keyword?: string | null
  connection_name?: string | null
  location?: string | null
  max_results?: number
  titles?: string[]
}

export interface PeopleDiscoverySpec {
  provider?: PeopleDiscoveryProvider
  connection_name?: string | null
  titles?: string[]
  max_per_company?: number
}

export interface EnrichmentStageSpec {
  provider: EnrichmentProvider
  connection_name: string
  merge_policy?: 'fill_missing' | 'overwrite'
  skip_if_complete?: boolean
}

export interface MessageStepSpec {
  channel: MessageChannel
  subject_template?: string | null
  body_template?: string | null
  message_template?: string | null
  connection_name?: string | null
  mode?: 'invite' | 'dm' | 'profile_view' | 'inmail'
  delay_after?: { amount: number; unit: 'minutes' | 'hours' | 'days' } | null
}

export interface CompanyScreeningSpec {
  connection_name: string
  prompt: string
}

export interface CampaignSpec {
  name: string
  timezone?: string
  target_contacts: number
  sources: CampaignSourceSpec[]
  people?: PeopleDiscoverySpec
  enrichment?: EnrichmentStageSpec[]
  company_screening?: CompanyScreeningSpec
  messages?: MessageStepSpec[]
  bounds?: ObjectiveBounds
  audience?: ObjectiveAudience
  verification_threshold?: number
}

export const canvas = {
  list: () => api.get<Workflow[]>('/canvas/workflows').then((r) => r.data),
  create: (name: string, timezone = 'UTC') =>
    api.post<Workflow>('/canvas/workflows', { name, timezone }).then((r) => r.data),
  templates: () => api.get<CampaignTemplateInfo[]>('/canvas/templates').then((r) => r.data),
  createFromTemplate: (templateId: string, name?: string, timezone = 'UTC') =>
    api
      .post<WorkflowDetail>('/canvas/workflows/from-template', { template_id: templateId, name, timezone })
      .then((r) => r.data),
  createFromGoal: (input: GoalWorkflowCreate) =>
    api.post<WorkflowDetail>('/canvas/workflows/from-goal', input).then((r) => r.data),
  createFromSpec: (input: CampaignSpec) =>
    api.post<WorkflowDetail>('/canvas/workflows/from-spec', input).then((r) => r.data),
  get: (id: UUID) => api.get<WorkflowDetail>(`/canvas/workflows/${id}`).then((r) => r.data),
  validation: (id: UUID) =>
    api.get<GraphValidation>(`/canvas/workflows/${id}/validation`).then((r) => r.data),
  update: (id: UUID, body: Partial<Pick<Workflow, 'name' | 'status' | 'timezone' | 'start_at' | 'end_at' | 'daily_cap' | 'earliest_hour' | 'latest_hour' | 'days_of_week'>>) =>
    api.patch<Workflow>(`/canvas/workflows/${id}`, body).then((r) => r.data),
  archive: (id: UUID) => api.delete(`/canvas/workflows/${id}`).then(() => undefined),
  // Hard-delete an ARCHIVED workflow + all its data (nodes/edges/leads/objectives).
  // 409 if not archived first — the two-step guard.
  deletePermanent: (id: UUID) => api.delete(`/canvas/workflows/${id}/permanent`).then(() => undefined),
  pool: (workflowId: UUID) =>
    api.get<SendingAccount[]>(`/canvas/workflows/${workflowId}/accounts`).then((r) => r.data),
  setPool: (workflowId: UUID, sendingAccountIds: UUID[]) =>
    api.put<SendingAccount[]>(`/canvas/workflows/${workflowId}/accounts`, { sending_account_ids: sendingAccountIds }).then((r) => r.data),

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

  // Run a workflow: enroll a seed lead at the entry node and fire it so the
  // pipeline begins. Returns the seed lead + correlation id to trace the run.
  run: (workflowId: UUID, startNodeId?: UUID) =>
    api
      .post<RunResponse>(`/canvas/workflows/${workflowId}/run`, startNodeId ? { start_node_id: startNodeId } : {})
      .then((r) => r.data),

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

export interface Task {
  id: UUID
  contact_id: UUID | null
  title: string
  due_date: ISODate | null
  priority: string
  status: string // 'open' | 'done'
  created_at: ISODate
}

// A lead's columns are additive per node, so it carries a computed identity +
// stage and a flattened ``fields`` bag keyed by the workflow's LeadColumn keys
// (see GET /projections/leads/columns).
export type LeadStage = 'new' | 'source' | 'company' | 'resolved' | 'verifying' | 'person'

export interface Lead {
  id: UUID
  contact_id: UUID | null
  workflow_id: UUID | null
  current_node_id: UUID | null
  status: string
  custom_fields: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
  identity: string
  stage: LeadStage
  fields: Record<string, unknown>
}

export type LeadColumnKind = 'text' | 'number' | 'url' | 'badge' | 'date'

export interface LeadColumn {
  key: string
  label: string
  path: string
  kind: LeadColumnKind
}

export interface LeadColumnsResponse {
  workflow_id: UUID | null
  columns: LeadColumn[]
}

// ── Lead journey (per-lead reconstruction of the distributed run) ─────────────
export interface JourneyEvent {
  occurred_at: ISODate
  event_type: string
  node_id: UUID | null
  node_label: string | null
}

export interface LineageLead {
  id: UUID
  identity: string
  status: string
  stage: LeadStage
}

export interface JourneyCost {
  total_usd: number
  by_kind: Record<string, number>
  calls: number
}

export interface LeadJourney {
  lead: Lead
  parent: LineageLead | null
  children: LineageLead[]
  timeline: JourneyEvent[]
  cost: JourneyCost
  status_reason: string
}

export interface ContactFilters {
  q?: string
  source?: string
  workflow_id?: UUID
  has_email?: boolean
  limit?: number
}

export interface ContactSummary {
  total: number
  with_email: number
  with_linkedin: number
  with_company: number
}

export interface LeadSummary {
  total: number
  active: number
  people: number
  companies: number
  hot: number
}

export interface CompanyFilters {
  q?: string
  industry?: string
  has_domain?: boolean
  limit?: number
}

export const projections = {
  contacts: (filters: ContactFilters | number = 100) => {
    // Back-compat: a bare number is treated as the limit.
    const params = typeof filters === 'number' ? { limit: filters } : filters
    return api.get<Contact[]>('/projections/contacts', { params }).then((r) => r.data)
  },
  contactSummary: (filters: Omit<ContactFilters, 'limit'> = {}) =>
    api.get<ContactSummary>('/projections/contacts/summary', { params: filters }).then((r) => r.data),
  contact: (id: UUID) => api.get<Contact>(`/projections/contacts/${id}`).then((r) => r.data),
  contactSources: () => api.get<string[]>('/projections/contacts/sources').then((r) => r.data),
  companies: (filters: CompanyFilters | number = 100) => {
    const params = typeof filters === 'number' ? { limit: filters } : filters
    return api.get<Company[]>('/projections/companies', { params }).then((r) => r.data)
  },
  deals: (params: { stage?: string; limit?: number } = {}) =>
    api.get<Deal[]>('/projections/deals', { params }).then((r) => r.data),
  tasks: (params: { status?: string; limit?: number } = {}) =>
    api.get<Task[]>('/projections/tasks', { params }).then((r) => r.data),
  completeTask: (id: UUID, done = true) =>
    api.post(`/projections/tasks/${id}/complete`, undefined, { params: { done } }).then((r) => r.data),
  leads: (params: { workflow_id?: UUID; include_source_batches?: boolean; limit?: number } = {}) =>
    api.get<Lead[]>('/projections/leads', { params }).then((r) => r.data),
  leadSummary: (params: { workflow_id?: UUID; include_source_batches?: boolean } = {}) =>
    api.get<LeadSummary>('/projections/leads/summary', { params }).then((r) => r.data),
  deleteContact: (id: UUID) => api.delete<void>(`/projections/contacts/${id}`).then(() => undefined),
  deleteCompany: (id: UUID) => api.delete<void>(`/projections/companies/${id}`).then(() => undefined),
  deleteLead: (id: UUID) => api.delete<void>(`/projections/leads/${id}`).then(() => undefined),
  leadJourney: (id: UUID) => api.get<LeadJourney>(`/projections/leads/${id}/journey`).then((r) => r.data),
  leadColumns: (workflowId?: UUID) =>
    api
      .get<LeadColumnsResponse>('/projections/leads/columns', {
        params: workflowId ? { workflow_id: workflowId } : undefined,
      })
      .then((r) => r.data),
  analytics: () => api.get<AnalyticsSummary>('/projections/analytics').then((r) => r.data),
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

export interface ReplySuggestion {
  draft: string
  source: string // 'llm' | 'template'
}

export interface ReplyAccepted {
  status: string
  channel: string
  correlation_id: UUID
}

export const inbox = {
  threads: (limit = 50) => api.get<InboxThread[]>('/inbox/threads', { params: { limit } }).then((r) => r.data),
  thread: (contactId: UUID, limit = 200) =>
    api.get<InboxMessage[]>(`/inbox/threads/${contactId}`, { params: { limit } }).then((r) => r.data),
  suggest: (contactId: UUID) =>
    api.post<ReplySuggestion>(`/inbox/threads/${contactId}/suggest`).then((r) => r.data),
  reply: (contactId: UUID, body: { body: string; subject?: string; channel?: string }) =>
    api.post<ReplyAccepted>(`/inbox/threads/${contactId}/reply`, body).then((r) => r.data),
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

export type SendChannelKind = 'email' | 'linkedin' | 'sms' | 'voice' | 'whatsapp' | 'instagram' | 'telegram'
export type SendingAccountStatus = 'active' | 'paused' | 'warming' | 'banned'

export interface SendingAccount {
  id: UUID
  connection_id: UUID
  provider: string
  channel_kind: SendChannelKind
  external_identity: string
  display_name: string | null
  daily_cap: number
  hourly_cap: number
  sends_today: number
  sends_this_hour: number
  status: SendingAccountStatus
  warmup_target: number | null
  last_used_at: ISODate | null
  health: Record<string, unknown>
  created_at: ISODate
  updated_at: ISODate
}

export interface SendingAccountCreate {
  channel_kind: SendChannelKind
  external_identity: string
  display_name?: string | null
  daily_cap?: number
  hourly_cap?: number
  warmup_target?: number | null
  status?: SendingAccountStatus
}

export interface SendingAccountUpdate {
  display_name?: string | null
  daily_cap?: number
  hourly_cap?: number
  warmup_target?: number | null
  status?: SendingAccountStatus
}

export interface SyncResult {
  synced: number
  accounts: SendingAccount[]
}

export const integrations = {
  list: (provider?: string) =>
    api.get<Connection[]>('/integrations', { params: provider ? { provider } : undefined }).then((r) => r.data),
  create: (body: ConnectionCreate) => api.post<Connection>('/integrations', body).then((r) => r.data),
  remove: (id: UUID) => api.delete(`/integrations/${id}`).then(() => undefined),
  allAccounts: () => api.get<SendingAccount[]>('/integrations/accounts').then((r) => r.data),
  accounts: (connectionId: UUID) =>
    api.get<SendingAccount[]>(`/integrations/${connectionId}/accounts`).then((r) => r.data),
  addAccount: (connectionId: UUID, body: SendingAccountCreate) =>
    api.post<SendingAccount>(`/integrations/${connectionId}/accounts`, body).then((r) => r.data),
  updateAccount: (accountId: UUID, body: SendingAccountUpdate) =>
    api.patch<SendingAccount>(`/integrations/accounts/${accountId}`, body).then((r) => r.data),
  removeAccount: (accountId: UUID) =>
    api.delete(`/integrations/accounts/${accountId}`).then(() => undefined),
  syncAccounts: (connectionId: UUID) =>
    api.post<SyncResult>(`/integrations/${connectionId}/accounts/sync`).then((r) => r.data),
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

// ── Approvals (human-in-the-loop queue, CONTRACT-005) ────────────────────────
export interface Approval {
  id: UUID
  lead_id: UUID
  node_id: UUID | null
  prompt: string
  draft: string | null
  status: string
  created_at: ISODate
}

export const approvals = {
  list: () => api.get<Approval[]>('/approvals').then((r) => r.data),
  updateDraft: (id: UUID, draft: string) =>
    api.patch(`/approvals/${id}/draft`, { draft }).then((r) => r.data),
  resolve: (id: UUID, handle: 'approved' | 'rejected') =>
    api.post(`/approvals/${id}/resolve`, { handle }).then((r) => r.data),
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
  identity: string | null
}

export interface LeadScoreSummary {
  total: number
  hot: number
  warm: number
  cold: number
  historical: number
}

export type AiJobKind = 'score' | 'compose' | 'enrich' | 'classify' | 'screen'
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
  scores: (params: { tier?: LeadTier; include_historical?: boolean; limit?: number } = {}) =>
    api.get<LeadScore[]>('/ai/scores', { params }).then((r) => r.data),
  score: (leadId: UUID) => api.get<LeadScore>(`/ai/scores/${leadId}`).then((r) => r.data),
  scoreSummary: () => api.get<LeadScoreSummary>('/ai/scores/summary').then((r) => r.data),
  jobs: (params: { kind?: AiJobKind; status?: AiJobStatus; limit?: number } = {}) =>
    api.get<AiJob[]>('/ai/jobs', { params }).then((r) => r.data),
  runJob: (body: AiJobCreate) =>
    api.post<{ job_id: UUID; kind: string; status: string; correlation_id: UUID }>('/ai/jobs', body).then((r) => r.data),
}
