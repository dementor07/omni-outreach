import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export interface BlacklistEntry {
  id: string
  entry_type: string
  value: string
  reason: string
  created_at: string
}

interface BlacklistListResponse {
  entries: BlacklistEntry[]
  total: number
  page: number
  page_size: number
}

export function useBlacklist(entryType?: string, search?: string, page = 1) {
  return useQuery({
    queryKey: ['blacklist', entryType, search, page],
    queryFn: async () => {
      const { data } = await api.get<BlacklistListResponse>('/blacklist', {
        params: { entry_type: entryType || undefined, search: search || undefined, page },
      })
      return data
    },
  })
}

export function useAddBlacklist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (entry: { entry_type: string; value: string; reason?: string }) => {
      const { data } = await api.post('/blacklist', entry)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['blacklist'] }),
  })
}

export function useRemoveBlacklist() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.delete(`/blacklist/${id}`)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['blacklist'] }),
  })
}
