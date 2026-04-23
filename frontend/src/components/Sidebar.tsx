import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Megaphone, Users, ListTodo, Settings, LogOut, Zap, Search, Database, Activity, ShieldOff, BarChart3, FileText, Inbox, UserCheck } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { clsx } from 'clsx'

const navItems = [
  { to: '/',              label: 'Overview',      icon: LayoutDashboard },
  { to: '/campaigns',    label: 'Campaigns',     icon: Megaphone },
  { to: '/leads',        label: 'Leads',         icon: Users },
  { to: '/queue',        label: 'Queue',         icon: ListTodo },
  { to: '/lead-sources', label: 'Lead Sources',  icon: Database },
  { to: '/activity',     label: 'Activity',      icon: Activity },
  { to: '/blacklist',    label: 'Blacklist',     icon: ShieldOff },
  { to: '/analytics',    label: 'Analytics',     icon: BarChart3 },
  { to: '/templates',    label: 'Templates',     icon: FileText },
  { to: '/inbox',        label: 'Inbox',         icon: Inbox },
  { to: '/approvals',    label: 'Approvals',     icon: UserCheck },
  { to: '/job-search',   label: 'Job Search',    icon: Search },
  { to: '/settings',     label: 'Settings',      icon: Settings },
]

export default function Sidebar() {
  const navigate = useNavigate()
  const approvalsCountQuery = useQuery<{ pending: number }>({
    queryKey: ['approvals-count'],
    queryFn: async () => (await api.get<{ pending: number }>('/approvals/count')).data,
    refetchInterval: 30_000,
  })
  const pending = approvalsCountQuery.data?.pending ?? 0

  function logout() {
    localStorage.removeItem('token')
    navigate('/login')
  }

  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-white dark:bg-slate-800 border-r border-slate-200 dark:border-slate-700 flex flex-col z-30">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-slate-100 dark:border-slate-700">
        <div className="flex items-center justify-center w-7 h-7 bg-sky-500 rounded-lg">
          <Zap size={14} className="text-white" fill="white" />
        </div>
        <div>
          <span className="block text-sm font-bold tracking-tight text-slate-900 dark:text-white">Omni</span>
          <span className="block text-[11px] uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">Control Plane</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {navItems.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors',
                isActive
                  ? 'bg-sky-50 dark:bg-sky-900/30 text-sky-600 dark:text-sky-400'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 hover:text-slate-900 dark:hover:text-white',
              )
            }
          >
            <Icon size={16} />
            <span className="flex-1">{label}</span>
            {to === '/approvals' && pending > 0 && (
              <span className="rounded-full bg-rose-500 text-white text-[10px] font-bold px-2 py-0.5 min-w-[20px] text-center">{pending}</span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-3 py-4 border-t border-slate-100 dark:border-slate-700">
        <button
          onClick={logout}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm font-medium text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-700 hover:text-slate-700 dark:hover:text-white transition-colors"
        >
          <LogOut size={16} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
