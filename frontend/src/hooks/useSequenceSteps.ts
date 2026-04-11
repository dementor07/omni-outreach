import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export type ChannelType = 'linkedin_invite' | 'linkedin_dm' | 'email' | 'voice'

export interface SequenceStep {
  id: string
  campaign_id: string
  step_order: number
  channel: ChannelType
  delay_days: number
  voice_agent_id: string | null
  email_account_id: string | null
  template_id: string | null
  voice_agent_name?: string | null
  email_account_email?: string | null
}

export interface StepTemplate {
  id: string
  step_id: string
  subject: string | null
  body: string
}

export interface StepCreatePayload {
  campaign_id: string
  step_order: number
  channel: ChannelType
  delay_days?: number
  voice_agent_id?: string | null
  email_account_id?: string | null
}

export interface StepUpdatePayload {
  step_order?: number
  channel?: ChannelType
  delay_days?: number
  voice_agent_id?: string | null
  email_account_id?: string | null
}

export interface TemplateUpsertPayload {
  step_id: string
  subject?: string | null
  body: string
}

export function useListSteps(campaignId?: string) {
  return useQuery({
    queryKey: ['sequence-steps', campaignId],
    enabled: !!campaignId,
    staleTime: 30_000,
    queryFn: async () => {
      const { data } = await api.get<SequenceStep[]>('/sequences', {
        params: { campaign_id: campaignId },
      })
      return data
    },
  })
}

export function useCreateStep() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: StepCreatePayload) => {
      const { data } = await api.post<SequenceStep>('/sequences', payload)
      return data
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['sequence-steps', data.campaign_id] })
    },
  })
}

export function useUpdateStep() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      id,
      campaignId,
      payload,
    }: {
      id: string
      campaignId: string
      payload: StepUpdatePayload
    }) => {
      const { data } = await api.put<SequenceStep>(`/sequences/${id}`, payload)
      return { ...data, campaignId }
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['sequence-steps', data.campaignId] })
    },
  })
}

export function useDeleteStep() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, campaignId }: { id: string; campaignId: string }) => {
      await api.delete(`/sequences/${id}`)
      return { campaignId }
    },
    onSuccess: ({ campaignId }) => {
      void queryClient.invalidateQueries({ queryKey: ['sequence-steps', campaignId] })
    },
  })
}

export function useGetTemplate(stepId?: string) {
  return useQuery({
    queryKey: ['template', stepId],
    enabled: !!stepId,
    staleTime: 30_000,
    queryFn: async () => {
      const { data } = await api.get<StepTemplate | null>('/templates', {
        params: { step_id: stepId },
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
      void queryClient.invalidateQueries({ queryKey: ['template', data.step_id] })
    },
  })
}
