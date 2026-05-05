import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'

export interface QueueTask {
  id: string
  campaign_id: string
  lead_id: string
  channel: string
  status: string
  scheduled_at?: string | null
  retry_count?: number
  failure_reason?: string | null
  first_name?: string | null
  last_name?: string | null
  linkedin_url?: string | null
}

export interface QueueStatsRow {
  channel: string
  status: string
  cnt: number
}

export function useQueueStats() {
  return useQuery({
    queryKey: ['queue-stats'],
    staleTime: 15_000,
    refetchInterval: 30_000,
    queryFn: async () => {
      const { data } = await api.get<{ stats: QueueStatsRow[] }>('/queue/stats')
      return data.stats
    },
  })
}

export function useQueueList(filters: { campaignId?: string; status?: string; limit?: number }) {
  const { campaignId, status, limit = 100 } = filters
  return useQuery({
    queryKey: ['queue', campaignId, status, limit],
    staleTime: 15_000,
    refetchInterval: 30_000,
    queryFn: async () => {
      const { data } = await api.get<{ tasks: QueueTask[] }>('/queue', {
        params: {
          campaign_id: campaignId || undefined,
          status: status || undefined,
          limit,
        },
      })
      return data.tasks
    },
  })
}

export function useRetryTask() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (taskId: string) => {
      await api.post(`/queue/${taskId}/retry`)
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['queue'] })
      void queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
    },
  })
}

export function useBulkRetryTasks() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (filters: { campaignId?: string; channel?: string }) => {
      await api.post('/queue/bulk-retry', null, {
        params: {
          campaign_id: filters.campaignId,
          channel: filters.channel,
        },
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['queue'] })
      void queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
    },
  })
}
