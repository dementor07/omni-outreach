import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'

export interface Lead {
  id: string
  campaign_id: string
  linkedin_url: string
  email?: string | null
  phone?: string | null
  first_name?: string | null
  last_name?: string | null
  headline?: string | null
  company?: string | null
  source?: string
  status?: 'active' | 'stopped'
  invited_at?: string | null
  accepted_at?: string | null
  replied_at?: string | null
  stopped_at?: string | null
  created_at?: string
}

export interface LeadTimelineEvent {
  event_type: string
  channel?: string | null
  meta?: Record<string, unknown> | null
  occurred_at?: string | null
}

export interface LeadDetail extends Lead {
  timeline: LeadTimelineEvent[]
}

export interface LeadImportPayload {
  linkedin_url: string
  email?: string | null
  phone?: string | null
  first_name?: string | null
  last_name?: string | null
  headline?: string | null
  company?: string | null
  source?: string
}

export interface LeadListResponse {
  leads: Lead[]
  total: number
  page: number
  page_size: number
}

export function useListLeads(campaignId?: string, page = 1, pageSize = 50) {
  return useQuery({
    queryKey: ['leads', campaignId, page, pageSize],
    enabled: !!campaignId,
    queryFn: async () => {
      const { data } = await api.get<LeadListResponse>('/leads', {
        params: { campaign_id: campaignId, page, page_size: pageSize },
      })
      return data
    },
  })
}

export function useGetLead(id?: string) {
  return useQuery({
    queryKey: ['lead', id],
    enabled: !!id,
    queryFn: async () => {
      const { data } = await api.get<LeadDetail>(`/leads/${id}`)
      return data
    },
  })
}

export function useImportLeads() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ campaignId, leads }: { campaignId: string; leads: LeadImportPayload[] }) => {
      const { data } = await api.post<{ imported: number; skipped: number }>(
        `/leads/import?campaign_id=${campaignId}`,
        leads,
      )
      return data
    },
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['leads', variables.campaignId] })
      void queryClient.invalidateQueries({ queryKey: ['campaign-stats', variables.campaignId] })
    },
  })
}

export function useStopLead() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ leadId, campaignId }: { leadId: string; campaignId: string }) => {
      await api.delete(`/leads/${leadId}`)
      return { leadId, campaignId }
    },
    onSuccess: ({ leadId, campaignId }) => {
      void queryClient.invalidateQueries({ queryKey: ['leads', campaignId] })
      void queryClient.invalidateQueries({ queryKey: ['lead', leadId] })
      void queryClient.invalidateQueries({ queryKey: ['campaign-stats', campaignId] })
      void queryClient.invalidateQueries({ queryKey: ['queue'] })
    },
  })
}
