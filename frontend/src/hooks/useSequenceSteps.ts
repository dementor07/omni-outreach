import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export type NodeType = 
  | 'trigger_start'
  | 'action_linkedin_invite'
  | 'action_linkedin_dm'
  | 'action_linkedin_inmail'
  | 'action_linkedin_profile_view'
  | 'action_email'
  | 'action_whatsapp'
  | 'action_sms'
  | 'action_instagram'
  | 'action_telegram'
  | 'action_voice'
  | 'action_webhook'
  | 'action_add_tag'
  | 'action_remove_tag'
  | 'action_enrich'
  | 'action_data_transform'
  | 'condition_replied'
  | 'condition_linkedin_distance'
  | 'condition_tag_exists'
  | 'condition_ai_screen'
  | 'condition_lead_source'
  | 'condition_has_field'
  | 'condition_reply_intent'
  | 'human_approval'
  | 'action_hot_lead_alert'
  | 'control_parallel_fork'
  | 'event_invite_accepted'
  | 'event_email_opened'
  | 'event_link_clicked'
  | 'delay'
  | 'wait_until'
  | 'split'
  | 'goal'
  | 'end'

export interface SequenceNode {
  id: string
  campaign_id: string
  node_type: NodeType
  position_x: number
  position_y: number
  data: any
  created_at: string
}

export interface SequenceEdge {
  id: string
  campaign_id: string
  source_node_id: string
  target_node_id: string
  source_handle: string
  target_handle: string
  created_at: string
}

export interface StepTemplate {
  id: string
  node_id: string
  subject: string | null
  body: string
}

export interface SaveGraphPayload {
  campaign_id: string
  nodes: {
    id?: string
    node_type: NodeType
    position_x: number
    position_y: number
    data?: any
  }[]
  edges: {
    source_node_id: string
    target_node_id: string
    source_handle?: string
    target_handle?: string
  }[]
}

export interface TemplateUpsertPayload {
  node_id: string
  subject?: string | null
  body: string
}

export function useGetGraph(campaignId?: string) {
  return useQuery({
    queryKey: ['sequence-graph', campaignId],
    enabled: !!campaignId,
    staleTime: 30_000,
    queryFn: async () => {
      const { data } = await api.get<{ nodes: SequenceNode[]; edges: SequenceEdge[] }>(`/sequences/${campaignId}`)
      return data
    },
  })
}

export function useSaveGraph() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: SaveGraphPayload) => {
      const { data } = await api.post('/sequences/save', payload)
      return { ...data, campaignId: payload.campaign_id }
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['sequence-graph', data.campaignId] })
    },
  })
}

export function useGetTemplate(nodeId?: string) {
  return useQuery({
    queryKey: ['template', nodeId],
    enabled: !!nodeId,
    staleTime: 30_000,
    queryFn: async () => {
      const { data } = await api.get<StepTemplate | null>('/templates', {
        params: { node_id: nodeId },
      })
      return data
    },
  })
}

export function useUpsertTemplate() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: TemplateUpsertPayload) => {
      const { data } = await api.post<StepTemplate>('/templates', payload)
      return data
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['template', data.node_id] })
    },
  })
}
