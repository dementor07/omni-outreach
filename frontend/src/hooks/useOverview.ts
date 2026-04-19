import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export interface OverviewStats {
  total_leads: number
  invited: number
  accepted: number
  sent: number
}

export interface DailyActivity {
  day: string
  status: string
  cnt: number
}

export interface ResponseRate {
  id: string
  name: string
  total: number
  invited: number
  accepted: number
  replied: number
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

export function useDailyActivity() {
  return useQuery({
    queryKey: ['daily-activity'],
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: false,
    queryFn: async () => {
      const { data } = await api.get<DailyActivity[]>('/overview/daily-activity')
      return data
    },
  })
}

export function useResponseRates() {
  return useQuery({
    queryKey: ['response-rates'],
    staleTime: 60_000,
    retry: false,
    queryFn: async () => {
      const { data } = await api.get<ResponseRate[]>('/overview/response-rates')
      return data
    },
  })
}
