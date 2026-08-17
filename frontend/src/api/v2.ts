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

// ── Message tone presets (TONE-PRESET-001) ───────────────────────────────────
export interface ToneWordCount {
  min?: number
  max?: number
  recommended?: number
  rationale?: string
}

export interface ToneSpec {
  tone_id: number
  tone: string
  description?: string
  personality_traits?: string[]
  word_count?: ToneWordCount
  opening_styles?: string[]
  value_delivery?: string[]
  closing_approaches?: string[]
  personalization_hooks?: string[]
  avoid?: string[]
  example_template?: { subject?: string; body?: string }
  [key: string]: unknown
}

export interface Tone {
  tone_id: number
  tone: string
  description: string
  spec: ToneSpec
  is_builtin: boolean
}

export const tones = {
  list: () => api.get<Tone[]>('/tones').then((r) => r.data),
  get: (toneId: number) => api.get<Tone>(`/tones/${toneId}`).then((r) => r.data),
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
  // Redeem an invite token. Mounted at the router root (the token encodes the
  // workspace). Returns a fresh JWT scoped to the joined workspace.
  acceptInvite: (token: string) =>
    api
      .post<{ workspace_id: UUID; role: string; access_token: string; token_type: string }>(
        '/workspaces/invites/accept',
        { token },
      )
      .then((r) => r.data),
  // Public: describe an invite so the accept page can show sign-in vs create-account.
  inviteInfo: (token: string) =>
    api
      .get<{
        valid: boolean
        reason?: string
        email?: string
        role?: string
        workspace_name?: string
        has_account?: boolean
      }>('/workspaces/invites/info', { params: { token } })
      .then((r) => r.data),
  // Public: create an account for the invited email + join the workspace in one step.
  registerAccept: (token: string, password: string) =>
    api
      .post<{ workspace_id: UUID; role: string; access_token: string; token_type: string }>(
        '/workspaces/invites/register-accept',
        { token, password },
      )
      .then((r) => r.data),
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

export type CampaignSourceProvider = 
  | 'naukri' | 'indeed' | 'linkedin_jobs'
  | 'greenhouse' | 'ashby' | 'smartrecruiters' | 'bamboohr' | 'workday' | 'icims' | 'lever' | 'workable' | 'recruitee' | 'personio' | 'rippling' | 'breezy'
  | 'searxng' | 'serper_search' | 'apollo' | 'clutch' | 'producthunt'
  | 'linkfinder_leads' | 'linkfinder_employees' | 'linkfinder_post_reactions'
export type PeopleDiscoveryProvider = 'searxng_people' | 'serper_people'
export type EnrichmentProvider = 'apollo' | 'proxycurl' | 'hunter'
export type MessageChannel = 'email' | 'linkedin' | 'sms' | 'whatsapp' | 'instagram' | 'telegram' | 'voice'

export interface CampaignSourceSpec {
  provider: CampaignSourceProvider
  query?: string | null
  keyword?: string | null
  connection_name?: string | null
  location?: string | null
  max_results?: number
  titles?: string[]
  input_data?: string | null
  domain?: string | null
  department?: string | null
  seniority?: string | null
  employee_count?: number | null
  fetch_count?: number
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
  // Voice (Retell agent call) only.
  retell_agent_id?: string | null
  delay_after?: { amount: number; unit: 'minutes' | 'hours' | 'days' } | null
  // Linkedin invite only: wait for the connection to be accepted before the next
  // step fires (compiles an event.invite_accepted wait). Never DM before connect.
  await_acceptance?: boolean
  accept_timeout_hours?: number
  // REPLIED-WINDOW-001: a reply within this many days counts as 'replied' and
  // stops the follow-up for this step. Default 30.
  reply_window_days?: number
  // COMPOSE-WIRE-001: when set, an ai.compose node drafts this message per lead
  // (the body becomes the generated {{ai_draft}}). Not valid on voice or invite.
  ai_compose?: string | null
  ai_tone?: 'professional' | 'casual' | 'warm' | 'direct'
  // TONE-PRESET-001: a structured tone preset (GET /tones); overrides ai_tone.
  ai_tone_id?: number | null
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

// OUTBOUND-FIRST-001: a contact attached to a campaign as an outbound recipient.
export interface AudienceContact {
  contact_id: UUID
  first_name?: string | null
  last_name?: string | null
  email?: string | null
  linkedin_url?: string | null
  company?: string | null
  added_at: ISODate
}

export interface AudienceMutation {
  added?: number
  removed?: number
  total: number
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
  validateSpec: (input: CampaignSpec) =>
    api.post<CampaignSpec>('/canvas/workflows/validate-spec', input).then((r) => r.data),
  // DYNAMIC-001: plain-language prompt → validated spec → compiled campaign.
  createFromPrompt: (prompt: string, dryRun = false, connectionName?: string) =>
    api
      .post<PromptWorkflowResult>('/canvas/workflows/from-prompt', {
        prompt,
        dry_run: dryRun,
        connection_name: connectionName || undefined,
      })
      .then((r) => r.data),
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

  // OUTBOUND-FIRST-001: the contacts a campaign reaches when it starts with an
  // outbound step (invite/DM/email a known list) instead of a discovery source.
  audience: (workflowId: UUID) =>
    api.get<AudienceContact[]>(`/canvas/workflows/${workflowId}/audience`).then((r) => r.data),
  addAudience: (workflowId: UUID, contactIds: UUID[]) =>
    api
      .post<AudienceMutation>(`/canvas/workflows/${workflowId}/audience`, { contact_ids: contactIds })
      .then((r) => r.data),
  removeAudience: (workflowId: UUID, contactId: UUID) =>
    api
      .delete<AudienceMutation>(`/canvas/workflows/${workflowId}/audience/${contactId}`)
      .then((r) => r.data),

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

export interface ContactCreateInput {
  email?: string | null
  linkedin_url?: string | null
  first_name?: string | null
  last_name?: string | null
  company?: string | null
  headline?: string | null
  phone?: string | null
  source?: string
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
  // OUTBOUND-FIRST-001: manually add a contact (deterministic id — upserts if the
  // person is later discovered by a source). The missing "add a contact" path.
  createContact: (input: ContactCreateInput) =>
    api.post<Contact>('/projections/contacts', input).then((r) => r.data),
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
  first_name: string | null
  last_name: string | null
  company: string | null
  headline: string | null
  last_message_at: ISODate
  message_count: number
  inbound_count: number
  sent_count: number
  last_inbound_at: ISODate | null
  last_classification: string | null
  last_snippet: string | null
  last_channel: string | null
}

export interface InboxNotification {
  id: UUID
  contact_id: UUID
  first_name: string | null
  last_name: string | null
  company: string | null
  channel: string
  snippet: string | null
  classification: string | null
  occurred_at: ISODate
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
  threads: (limit = 50, workflowId?: UUID) =>
    api.get<InboxThread[]>('/inbox/threads', { params: { limit, workflow_id: workflowId } }).then((r) => r.data),
  thread: (contactId: UUID, limit = 200) =>
    api.get<InboxMessage[]>(`/inbox/threads/${contactId}`, { params: { limit } }).then((r) => r.data),
  notifications: (limit = 20) =>
    api.get<InboxNotification[]>('/inbox/notifications', { params: { limit } }).then((r) => r.data),
  suggest: (contactId: UUID) =>
    api.post<ReplySuggestion>(`/inbox/threads/${contactId}/suggest`).then((r) => r.data),
  reply: (contactId: UUID, body: { body: string; subject?: string; channel?: string }) =>
    api.post<ReplyAccepted>(`/inbox/threads/${contactId}/reply`, body).then((r) => r.data),
  // MSG-EDIT-001 — corrects THIS workspace's record of a message. It cannot change
  // what the recipient received; the original is kept and the bubble shows as edited.
  editMessage: (contactId: UUID, messageId: UUID, body: { body: string; reason?: string }) =>
    api.patch<{ message_id: UUID; edited: boolean; original_body: string }>(
      `/inbox/threads/${contactId}/messages/${messageId}`, body,
    ).then((r) => r.data),
  revertMessage: (contactId: UUID, messageId: UUID) =>
    api.delete<{ message_id: UUID; edited: boolean; body: string }>(
      `/inbox/threads/${contactId}/messages/${messageId}`,
    ).then((r) => r.data),
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
  campaign_id: UUID | null
  campaign_name: string | null
  prospect_name: string | null
  prospect_linkedin_url: string | null
  prospect_company: string | null
  sending_account_id: string | null
  sending_account_name: string | null
  evidence_sources: ApprovalEvidence[]
  compose_context: ApprovalComposeContext | null
}

export interface ApprovalEvidence {
  kind: 'hiring' | 'post' | 'website' | 'profile'
  label: string
  url: string | null
  excerpt: string | null
}

export interface ApprovalComposeContext {
  node_id: UUID
  instruction: string
  channel: string
  tone: string
  max_words: number
  model: string | null
  provider: string
}

export interface RewriteDirective {
  start: number
  end: number
  selected_text: string
  instruction: string
}

export interface ApprovalRegenerateInput {
  original_draft: string
  campaign_instruction?: string
  rewrite_note?: string
  directives?: RewriteDirective[]
  tone?: string
  channel?: string
  max_words?: number
  model?: string
}

export interface AiJobAccepted {
  job_id: UUID
  kind: string
  status: string
  correlation_id: UUID
}

export const approvals = {
  list: (campaignId?: UUID) =>
    api.get<Approval[]>('/approvals', { params: { campaign_id: campaignId } }).then((r) => r.data),
  updateDraft: (id: UUID, draft: string) =>
    api.patch(`/approvals/${id}/draft`, { draft }).then((r) => r.data),
  regenerate: (id: UUID, input: ApprovalRegenerateInput) =>
    api.post<AiJobAccepted>(`/approvals/${id}/regenerate`, input).then((r) => r.data),
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

// ── Developer: API keys + outbound webhook subscriptions (N8N-001) ────────────
export interface ApiKey {
  id: UUID
  name: string
  key_prefix: string
  last_used_at: ISODate | null
  revoked_at: ISODate | null
  created_at: ISODate
}

export interface ApiKeyCreated {
  id: UUID
  name: string
  key: string // the RAW key — shown ONCE
  key_prefix: string
  created_at: ISODate
}

export interface WebhookSubscription {
  id: UUID
  url: string
  event_types: string[]
  active: boolean
  last_delivery_at: ISODate | null
  last_status: number | null
  created_at: ISODate
  secret?: string | null // returned only on create
}

export interface WebhookSubscriptionCreate {
  url: string
  event_types?: string[]
  secret?: string
}

export interface WebhookSubscriptionUpdate {
  url?: string
  event_types?: string[]
  active?: boolean
}

// The customer-facing events an outbound webhook can subscribe to. Mirrors the
// backend allow-list (app.services.webhook_events.ALLOWED_EVENTS, minus ping).
export const WEBHOOK_EVENT_TYPES = [
  'lead.replied',
  'invite.accepted',
  'campaign.run.completed',
  'lead.enriched',
  'lead.hot',
] as const

export const apiKeys = {
  list: () => api.get<ApiKey[]>('/api-keys').then((r) => r.data),
  create: (name: string) => api.post<ApiKeyCreated>('/api-keys', { name }).then((r) => r.data),
  revoke: (id: UUID) => api.delete<void>(`/api-keys/${id}`).then(() => undefined),
}

export const webhookSubscriptions = {
  list: () => api.get<WebhookSubscription[]>('/webhook-subscriptions').then((r) => r.data),
  create: (body: WebhookSubscriptionCreate) =>
    api.post<WebhookSubscription>('/webhook-subscriptions', body).then((r) => r.data),
  update: (id: UUID, body: WebhookSubscriptionUpdate) =>
    api.patch<WebhookSubscription>(`/webhook-subscriptions/${id}`, body).then((r) => r.data),
  remove: (id: UUID) => api.delete<void>(`/webhook-subscriptions/${id}`).then(() => undefined),
  test: (id: UUID) =>
    api
      .post<{ delivered: boolean; status_code: number | null; error: string | null }>(
        `/webhook-subscriptions/${id}/test`,
      )
      .then((r) => r.data),
}

// ── Unipile control plane (UNIPILE-FULL group C/D) ────────────────────────────
// Workspace-level Unipile reads/CRUD the frontend calls directly (account
// health, inbox reads, inmail-balance, native webhook CRUD). Shapes are
// passthrough Unipile JSON, so they're typed loosely as `unknown`.
export const unipile = {
  accounts: () => api.get<unknown>('/unipile/accounts').then((r) => r.data),
  account: (accountId: string) => api.get<unknown>(`/unipile/accounts/${accountId}`).then((r) => r.data),
  resync: (accountId: string) => api.post<unknown>(`/unipile/accounts/${accountId}/resync`).then((r) => r.data),
  reconnect: (accountId: string) =>
    api.post<unknown>(`/unipile/accounts/${accountId}/reconnect`).then((r) => r.data),
  restart: (accountId: string) => api.post<unknown>(`/unipile/accounts/${accountId}/restart`).then((r) => r.data),
  inmailBalance: (accountId: string) =>
    api.get<unknown>('/unipile/inmail-balance', { params: { account_id: accountId } }).then((r) => r.data),
  companyProfile: (companyId: string, accountId: string) =>
    api.get<unknown>(`/unipile/company/${companyId}`, { params: { account_id: accountId } }).then((r) => r.data),
  chats: (accountId: string, params: { cursor?: string; limit?: number } = {}) =>
    api.get<unknown>('/unipile/chats', { params: { account_id: accountId, ...params } }).then((r) => r.data),
  chatMessages: (chatId: string, params: { cursor?: string; limit?: number } = {}) =>
    api.get<unknown>(`/unipile/chats/${chatId}/messages`, { params }).then((r) => r.data),
  chatAttendees: (chatId: string) =>
    api.get<unknown>(`/unipile/chats/${chatId}/attendees`).then((r) => r.data),
  webhooks: () => api.get<unknown>('/unipile/webhooks').then((r) => r.data),
  registerWebhook: (events?: string[]) =>
    api.post<unknown>('/unipile/webhooks', { events }).then((r) => r.data),
  deleteWebhook: (webhookId: string) =>
    api.delete<void>(`/unipile/webhooks/${webhookId}`).then(() => undefined),
}

// ── Dynamic views (DYNAMIC-001) ───────────────────────────────────────────────
// Interfaces-as-data: a view is a stored layout of widget instances, each
// binding a constrained QuerySpec to a renderer. Views are authored by the
// user, the AI view architect (POST /views/generate), or an external agent.

export interface ViewQueryFilter {
  field: string
  op?: 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte' | 'contains' | 'in' | 'not_in' | 'is_null' | 'not_null'
  value?: unknown
}

export interface ViewQueryMetric {
  fn: 'count' | 'count_distinct' | 'sum' | 'avg' | 'min' | 'max'
  field?: string
  alias?: string
}

export interface ViewQuerySpec {
  entity: string
  filters?: ViewQueryFilter[]
  select?: string[]
  group_by?: string[]
  metrics?: ViewQueryMetric[]
  time_bucket?: 'day' | 'week' | 'month' | null
  sort?: { field: string; dir: 'asc' | 'desc' }[]
  limit?: number
}

export type WidgetType = 'stat' | 'table' | 'bar_chart' | 'line_chart' | 'list'

/**
 * DYNAMIC-003 — chart presentation options. Presentation only: these never
 * change what a query returns, so a widget can't claim something its data
 * doesn't support. Series COLOUR is deliberately absent — slots are assigned by
 * position from one validated palette, and that ordering is what keeps adjacent
 * series distinguishable under colour-vision deficiency.
 */
export interface WidgetOptions {
  legend?: boolean | null
  stacked?: boolean
  value_labels?: boolean
  x_label?: string | null
  y_label?: string | null
  series_labels?: Record<string, string>
}

export interface WidgetInstance {
  id: string
  type: WidgetType
  title: string
  query: ViewQuerySpec
  width?: number
  height?: number
  options?: WidgetOptions
}

export interface ViewDef {
  id: UUID
  name: string
  description: string
  icon: string
  layout: WidgetInstance[]
  prompt: string | null
  created_by: 'user' | 'ai' | 'api'
  position: number
  updated_at: ISODate
}

export interface ViewAnnotationInput {
  widget_id: string
  note: string
}

export interface ViewAuthoringConnection {
  id: UUID
  provider: string
  name: string
  adapter: 'anthropic' | 'openai_responses' | 'openai_compatible' | 'gemini'
  default_model: string
}

export interface ViewCandidate {
  name: string
  description: string
  icon: string
  layout: WidgetInstance[]
}

export type ViewAuthorRequest =
  | {
      source: 'connection'
      annotations: ViewAnnotationInput[]
      proposal_id: UUID
    }
  | {
      source: 'harness'
      annotations: ViewAnnotationInput[]
      proposal_id: UUID
    }
  | {
      source: 'import'
      annotations: ViewAnnotationInput[]
      proposal_id: UUID
    }

export type ViewProposalRequest =
  | {
      source: 'connection'
      instruction: string
      annotations: ViewAnnotationInput[]
      connection_id: UUID
      model?: string
    }
  | {
      source: 'harness'
      instruction: string
      annotations: ViewAnnotationInput[]
      harness_id: string
    }
  | {
      source: 'import'
      instruction?: string
      annotations?: ViewAnnotationInput[]
      candidate_view: ViewCandidate
    }

export type AgentJobStatus = 'queued' | 'working' | 'succeeded' | 'failed' | 'cancelled' | 'expired'

export interface AgentHarnessWidgetReview {
  widget_id: string
  before_title: string | null
  after_title: string | null
  before_rows: Record<string, unknown>[]
  after_rows: Record<string, unknown>[]
  query_changed: boolean
}

export interface AgentHarnessReviewIssue extends Record<string, unknown> {
  code: string
  severity: 'warning' | 'error'
  message: string
  widget_id?: string
  widget_ids?: string[]
}

export interface AgentHarnessReview {
  captured_at?: ISODate
  all_queries_valid?: boolean
  ready_to_apply?: boolean
  changed_widgets?: AgentHarnessWidgetReview[]
  warnings?: AgentHarnessReviewIssue[]
  blocking_issues?: AgentHarnessReviewIssue[]
}

export interface AgentHarnessJob {
  id: UUID
  kind: string
  target_type: string
  target_id: UUID
  status: AgentJobStatus
  result: ViewCandidate | Record<string, unknown> | null
  progress: { at: ISODate; message: string }[]
  error: string | null
  requested_harness_id: string | null
  harness_id: string | null
  origin: 'harness' | 'connection' | 'import'
  target_version: ISODate | null
  lease_expires_at: ISODate | null
  review: AgentHarnessReview | null
  attempts: number
  claimed_at: ISODate | null
  last_heartbeat_at: ISODate | null
  completed_at: ISODate | null
  applied_at: ISODate | null
  expires_at: ISODate
  created_at: ISODate
  updated_at: ISODate
}

export interface AgentHarnessWorker {
  harness_id: string
  state: 'listening' | 'working' | 'waiting'
  job_id: UUID | null
  last_seen_at: ISODate
  active_until: ISODate
}

export interface ViewQueryResult {
  columns: string[]
  rows: Record<string, unknown>[]
}

// DYNAMIC-001: response of POST /canvas/workflows/from-prompt — the generated
// spec plus (unless dry_run) the created workflow detail.
export interface PromptWorkflowResult {
  spec: CampaignSpec
  detail: WorkflowDetail | null
}

export const views = {
  list: () => api.get<ViewDef[]>('/views').then((r) => r.data),
  // DYNAMIC-002: the home/Overview view, seeded on first request. The Overview
  // page renders this and falls back to the static page if it fails.
  default: () => api.get<ViewDef>('/views/default').then((r) => r.data),
  get: (id: UUID) => api.get<ViewDef>(`/views/${id}`).then((r) => r.data),
  create: (body: { name: string; description?: string; icon?: string; layout: WidgetInstance[] }) =>
    api.post<ViewDef>('/views', body).then((r) => r.data),
  update: (id: UUID, body: Partial<Pick<ViewDef, 'name' | 'description' | 'icon' | 'layout' | 'position'>>) =>
    api.patch<ViewDef>(`/views/${id}`, body).then((r) => r.data),
  remove: (id: UUID) => api.delete(`/views/${id}`).then(() => undefined),
  generate: (prompt: string) => api.post<ViewDef>('/views/generate', { prompt }).then((r) => r.data),
  authoringConnections: () => api.get<ViewAuthoringConnection[]>('/views/authoring/connections').then((r) => r.data),
  validateCandidate: (candidate: ViewCandidate) => api.post<ViewCandidate>('/views/validate', candidate).then((r) => r.data),
  createProposal: (id: UUID, body: ViewProposalRequest) =>
    api.post<AgentHarnessJob>(`/views/${id}/proposals`, body).then((r) => r.data),
  author: (id: UUID, body: ViewAuthorRequest) => api.post<ViewDef>(`/views/${id}/author`, body).then((r) => r.data),
  createHarnessJob: (id: UUID, body: { instruction: string; annotations: ViewAnnotationInput[]; harness_id: string }) =>
    api.post<AgentHarnessJob>(`/views/${id}/harness-jobs`, body).then((r) => r.data),
  grounding: (id: UUID) =>
    api.get<Record<string, unknown>>(`/views/${id}/grounding`).then((r) => r.data),
  openProposal: (id: UUID) =>
    api.get<AgentHarnessJob | null>(`/views/${id}/open-proposal`).then((r) => r.data),
  query: (spec: ViewQuerySpec) => api.post<ViewQueryResult>('/views/query', spec).then((r) => r.data),
  widgetCatalog: () => api.get<Record<string, unknown>>('/views/widgets').then((r) => r.data),
}

export const agentHarness = {
  workerStatus: () => api.get<{ available: boolean; workers: AgentHarnessWorker[] }>('/agent-harness/workers/status').then((r) => r.data),
  workers: () => api.get<AgentHarnessWorker[]>('/agent-harness/workers').then((r) => r.data),
  jobs: () => api.get<AgentHarnessJob[]>('/agent-harness/jobs', { params: { limit: 50 } }).then((r) => r.data),
  job: (id: UUID) => api.get<AgentHarnessJob>(`/agent-harness/jobs/${id}`).then((r) => r.data),
  cancel: (id: UUID) => api.post<AgentHarnessJob>(`/agent-harness/jobs/${id}/cancel`).then((r) => r.data),
  discard: (id: UUID) => api.post<AgentHarnessJob>(`/agent-harness/jobs/${id}/discard`).then((r) => r.data),
}
