import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export interface LibraryTemplate {
  id: string
  name: string
  channel: string
  category: string
  subject: string | null
  body: string
  variables: string[]
  is_public: boolean
  created_at: string
  updated_at: string
}

export function useTemplateLibrary(channel?: string, category?: string, search?: string) {
  return useQuery({
    queryKey: ['template-library', channel, category, search],
    queryFn: async () => {
      const { data } = await api.get<LibraryTemplate[]>('/template-library', {
        params: { channel: channel || undefined, category: category || undefined, search: search || undefined },
      })
      return data
    },
  })
}

export function useCreateLibraryTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (payload: { name: string; channel: string; category: string; subject?: string; body: string }) => {
      const { data } = await api.post('/template-library', payload)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['template-library'] }),
  })
}

export function useUpdateLibraryTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: { id: string } & Partial<{ name: string; channel: string; category: string; subject: string; body: string }>) => {
      const { data } = await api.put(`/template-library/${id}`, payload)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['template-library'] }),
  })
}

export function useDeleteLibraryTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) => {
      const { data } = await api.delete(`/template-library/${id}`)
      return data
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['template-library'] }),
  })
}
