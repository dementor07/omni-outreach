import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export interface InboxMessage {
  id: string
  lead_id: string
  campaign_id: string
  channel: string
  event_type: string
  meta: Record<string, any> | null
  occurred_at: string
  first_name: string | null
  last_name: string | null
  company: string | null
  linkedin_url: string | null
  lead_email: string | null
}

interface InboxResponse {
  messages: InboxMessage[]
  total: number
  page: number
  page_size: number
}

export function useInbox(channel?: string, campaignId?: string, category?: string, page = 1) {
  return useQuery({
    queryKey: ['inbox', channel, campaignId, category, page],
    queryFn: async () => {
      const { data } = await api.get<InboxResponse>('/inbox', {
        params: { channel: channel || undefined, campaign_id: campaignId || undefined, category: category || undefined, page },
      })
      return data
    },
    refetchInterval: 15_000,
  })
}

export function useInboxStats() {
  return useQuery({
    queryKey: ['inbox-stats'],
    queryFn: async () => {
      const { data } = await api.get<{ total: number; by_channel: { channel: string; cnt: number }[] }>('/inbox/stats')
      return data
    },
    refetchInterval: 30_000,
  })
}
