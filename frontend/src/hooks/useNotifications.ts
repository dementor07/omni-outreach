import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

export interface Notification {
  id: string
  type: string
  title: string
  body?: string
  link?: string
  is_read: boolean
  created_at: string
}

export function useNotifications() {
  const queryClient = useQueryClient()
  const [unreadCount, setUnreadCount] = useState(0)
  const eventSourceRef = useRef<EventSource | null>(null)

  const query = useQuery({
    queryKey: ['notifications'],
    queryFn: async () => {
      const { data } = await api.get<{ notifications: Notification[]; unread_count: number }>('/notifications?limit=30')
      setUnreadCount(data.unread_count)
      return data
    },
    refetchInterval: 60_000,
  })

  // SSE connection for real-time push
  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) return

    const es = new EventSource(`/api/notifications/stream?token=${token}`)
    eventSourceRef.current = es

    es.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.type === 'connected') return
        setUnreadCount((c) => c + 1)
        queryClient.invalidateQueries({ queryKey: ['notifications'] })
      } catch {
        // ignore parse errors
      }
    }

    es.onerror = () => {
      es.close()
      // reconnect after 5s
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['notifications'] })
      }, 5000)
    }

    return () => {
      es.close()
      eventSourceRef.current = null
    }
  }, [queryClient])

  const markRead = useMutation({
    mutationFn: async (id: string) => {
      await api.post(`/notifications/${id}/read`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  const markAllRead = useMutation({
    mutationFn: async () => {
      await api.post('/notifications/read-all')
    },
    onSuccess: () => {
      setUnreadCount(0)
      queryClient.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  return {
    notifications: query.data?.notifications ?? [],
    unreadCount,
    isLoading: query.isLoading,
    markRead,
    markAllRead,
  }
}
