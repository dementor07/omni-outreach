import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export interface CampaignAnalytics {
  funnel: {
    total_leads: number
    active: number
    invited: number
    accepted: number
    replied: number
    stopped: number
  }
  rates: {
    invite_rate: number
    accept_rate: number
    reply_rate: number
  }
  event_counts: { event_type: string; cnt: number }[]
  channel_breakdown: { channel: string; cnt: number }[]
  daily_activity: { day: string; events: number; unique_leads: number }[]
}

export function useCampaignAnalytics(campaignId?: string) {
  return useQuery({
    queryKey: ['analytics', campaignId],
    enabled: !!campaignId,
    queryFn: async () => {
      const { data } = await api.get<CampaignAnalytics>(`/analytics/${campaignId}`)
      return data
    },
    refetchInterval: 60_000,
  })
}
