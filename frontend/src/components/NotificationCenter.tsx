import { useState, useRef, useEffect } from 'react'
import { Bell, Check, CheckCheck, ExternalLink } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { clsx } from 'clsx'
import { useNotifications, type Notification } from '../hooks/useNotifications'
import { timeAgo } from '../lib/time'

const TYPE_COLORS: Record<string, string> = {
  reply: 'bg-emerald-500',
  failure: 'bg-rose-500',
  campaign: 'bg-sky-500',
  lead: 'bg-amber-500',
  system: 'bg-slate-500',
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { notifications, unreadCount, markRead, markAllRead } = useNotifications()

  // Close on click outside
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  function handleClick(notif: Notification) {
    if (!notif.is_read) markRead.mutate(notif.id)
    if (notif.link) {
      navigate(notif.link)
      setOpen(false)
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white"
        aria-label="Notifications"
      >
        <Bell size={15} />
        {unreadCount > 0 && (
          <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-rose-500 ring-2 ring-white dark:ring-slate-950" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-11 z-50 w-96 rounded-2xl border border-slate-200 bg-white shadow-xl shadow-slate-200/50">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
            <h3 className="text-sm font-semibold text-slate-900">Notifications</h3>
            {unreadCount > 0 && (
              <button
                onClick={() => markAllRead.mutate()}
                className="flex items-center gap-1 text-xs font-medium text-sky-500 hover:text-sky-600"
              >
                <CheckCheck size={12} />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-96 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="py-12 text-center text-sm text-slate-400">No notifications yet</div>
            ) : (
              notifications.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleClick(n)}
                  className={clsx(
                    'flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-50',
                    !n.is_read && 'bg-sky-50/50',
                  )}
                >
                  <div className={clsx('mt-1 h-2 w-2 shrink-0 rounded-full', TYPE_COLORS[n.type] || TYPE_COLORS.system)} />
                  <div className="min-w-0 flex-1">
                    <p className={clsx('text-sm', n.is_read ? 'text-slate-600' : 'font-medium text-slate-900')}>
                      {n.title}
                    </p>
                    {n.body && (
                      <p className="mt-0.5 text-xs text-slate-400 line-clamp-2">{n.body}</p>
                    )}
                    <p className="mt-1 text-[11px] text-slate-400">{timeAgo(n.created_at)}</p>
                  </div>
                  {n.link && <ExternalLink size={12} className="mt-1 shrink-0 text-slate-300" />}
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
