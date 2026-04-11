import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export interface OverviewStats {
  total_leads: number
  invited: number
  accepted: number
  sent: number
}

export function useOverviewStats() {
  return useQuery({
    queryKey: ['overview-stats'],
    staleTime: 30_000,
    refetchInterval: 30_000,
    retry: false,
    queryFn: async () => {
      const { data } = await api.get<OverviewStats>('/overview/stats')
      return data
    },
  })
}
