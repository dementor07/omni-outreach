import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'

export interface Campaign {
  id: string
  name: string
  status?: 'active' | 'paused' | 'archived'
  daily_lead_cap: number
  invite_daily_cap: number
  simulation_mode: boolean
  timezone: string
  active_hours_start: number
  active_hours_end: number
  screening_prompt?: string | null
  created_at?: string
}

export interface CampaignStats {
  total: number
  active: number
  invited: number
  accepted: number
  stopped: number
}

export interface CampaignPayload {
  name: string
  daily_lead_cap: number
  invite_daily_cap: number
  simulation_mode: boolean
  timezone: string
  active_hours_start: number
  active_hours_end: number
  screening_prompt?: string | null
  status?: string
}

export function useListCampaigns() {
  return useQuery({
    queryKey: ['campaigns'],
    queryFn: async () => {
      const { data } = await api.get<Campaign[]>('/campaigns')
      return data
    },
  })
}

export function useGetCampaign(id?: string) {
  return useQuery({
    queryKey: ['campaign', id],
    enabled: !!id,
    queryFn: async () => {
      const { data } = await api.get<Campaign>(`/campaigns/${id}`)
      return data
    },
  })
}

export function useCampaignStats(id?: string) {
  return useQuery({
    queryKey: ['campaign-stats', id],
    enabled: !!id,
    queryFn: async () => {
      const { data } = await api.get<CampaignStats>(`/campaigns/${id}/stats`)
      return data
    },
  })
}

export function useCreateCampaign() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: CampaignPayload) => {
      const { data } = await api.post<Campaign>('/campaigns', payload)
      return data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}

export function useUpdateCampaign() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, payload }: { id: string; payload: Partial<CampaignPayload> }) => {
      const { data } = await api.put<Campaign>(`/campaigns/${id}`, payload)
      return data
    },
    onSuccess: (_, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      void queryClient.invalidateQueries({ queryKey: ['campaign', variables.id] })
      void queryClient.invalidateQueries({ queryKey: ['campaign-stats', variables.id] })
    },
  })
}

export function useDeleteCampaign() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/campaigns/${id}`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
    },
  })
}
