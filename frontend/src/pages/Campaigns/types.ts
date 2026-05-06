import { NodeType } from '../../hooks/useSequenceSteps'

export type CampaignTab = 'leads' | 'queue' | 'sequence' | 'sources' | 'settings'

export interface RetellPrompt {
  begin_message: string;
  general_prompt: string;
  llm_id: string;
  model: string;
}

export interface CampaignConfig {
  id: string
  campaign_id: string
  source_type: string
  source_display_name: string
  source_available: boolean
  cron_schedule: string | null
  last_run_at: string | null
  label: string | null
  created_at: string
}

export interface CampaignRun {
  id: string
  source_type: string
  status: 'pending' | 'running' | 'done' | 'failed'
  leads_found: number
  leads_added: number
  started_at: string
  triggered_by?: string
}

export type EmailAccount = { id: string; from_name: string; from_email: string }
export type VoiceAgent = { id: string; name: string; retell_agent_id: string }
export type LinkedInAccount = { id: string; name: string; unipile_id: string; is_active: boolean }

export interface NotificationChannel {
  id: string
  channel_type: 'slack' | 'email'
  name: string
  is_active: boolean
}

export interface CampaignPayload {
  name: string
  daily_lead_cap: number
  invite_daily_cap: number
  simulation_mode: boolean
  timezone: string
  active_hours_start: number
  active_hours_end: number
  screening_prompt: string
  sequence_mode: 'sequential' | 'canvas'
}
