import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Megaphone, Users, ListTodo, Settings, LogOut, Zap,
  Search, Database, Activity, ShieldOff, BarChart3, FileText, Inbox,
  UserCheck, ChevronRight,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { clsx } from 'clsx'

type NavItem = { to: string; label: string; icon: React.ElementType; badge?: 'count' }
type NavGroup = { label: string | null; items: NavItem[] }

const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { to: '/',          label: 'Overview',   icon: LayoutDashboard },
      { to: '/campaigns', label: 'Campaigns',  icon: Megaphone },
      { to: '/inbox',     label: 'Inbox',      icon: Inbox },
      { to: '/queue',     label: 'Queue',      icon: ListTodo },
      { to: '/approvals', label: 'Approvals',  icon: UserCheck, badge: 'count' },
    ],
  },
  {
    label: 'Data',
    items: [
      { to: '/leads',        label: 'Leads',        icon: Users },
      { to: '/lead-sources', label: 'Lead Sources',  icon: Database },
      { to: '/job-search',   label: 'Job Search',    icon: Search },
      { to: '/templates',    label: 'Templates',     icon: FileText },
      { to: '/blacklist',    label: 'Blacklist',     icon: ShieldOff },
    ],
  },
  {
    label: 'Insights',
    items: [
      { to: '/analytics', label: 'Analytics', icon: BarChart3 },
      { to: '/activity',  label: 'Activity',  icon: Activity },
    ],
  },
  {
    label: 'System',
    items: [
      { to: '/style-guide', label: 'Style guide', icon: Zap },
    ],
  },
]

interface SidebarProps {
  collapsed?: boolean
}

export default function Sidebar({ collapsed = false }: SidebarProps) {
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
    <aside
      className={clsx(
        'flex h-screen flex-col border-r border-slate-200 bg-white transition-[width] duration-200 dark:border-slate-800 dark:bg-slate-950',
        collapsed ? 'w-16' : 'w-60',
      )}
    >
      {/* Logo lockup */}
      <div className={clsx('flex items-center gap-2.5 border-b border-slate-100 px-4 py-4 dark:border-slate-800', collapsed && 'justify-center px-0')}>
        <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-brand-500 text-white shadow-sm shadow-brand-500/30">
          <Zap size={15} fill="currentColor" />
        </div>
        {!collapsed && (
          <div className="min-w-0">
            <div className="text-sm font-bold tracking-tight text-slate-900 dark:text-white">Omni</div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">Control plane</div>
          </div>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-4 overflow-y-auto px-2 py-3">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi}>
            {group.label && !collapsed && (
              <p className="px-2.5 pb-1 text-[9px] font-bold uppercase tracking-[0.2em] text-slate-400 dark:text-slate-500">
                {group.label}
              </p>
            )}
            <div className="space-y-0.5">
              {group.items.map(({ to, label, icon: Icon, badge }) => {
                const showBadge = badge === 'count' && pending > 0
                return (
                  <NavLink
                    key={to}
                    to={to}
                    end={to === '/'}
                    className={({ isActive }) =>
                      clsx(
                        'group relative flex w-full items-center rounded-lg text-sm font-medium transition-colors',
                        collapsed ? 'h-9 justify-center px-0' : 'gap-2.5 px-2.5 py-1.5',
                        isActive
                          ? 'bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300'
                          : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
                      )
                    }
                    title={collapsed ? label : undefined}
                  >
                    {({ isActive }) => (
                      <>
                        <Icon size={16} />
                        {!collapsed && <span className="flex-1 truncate text-left">{label}</span>}
                        {!collapsed && showBadge && (
                          <span className="rounded-md bg-rose-500 px-1.5 py-0.5 text-[10px] font-bold tabular-nums text-white">
                            {pending}
                          </span>
                        )}
                        {collapsed && showBadge && (
                          <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-rose-500 ring-2 ring-white dark:ring-slate-950" />
                        )}
                        {isActive && !collapsed && <ChevronRight size={12} className="text-brand-400" />}
                      </>
                    )}
                  </NavLink>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="space-y-0.5 border-t border-slate-100 px-2 py-3 dark:border-slate-800">
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            clsx(
              'flex w-full items-center rounded-lg text-sm font-medium transition-colors',
              collapsed ? 'h-9 justify-center px-0' : 'gap-2.5 px-2.5 py-1.5',
              isActive
                ? 'bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300'
                : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
            )
          }
          title="Settings"
        >
          <Settings size={16} />
          {!collapsed && <span>Settings</span>}
        </NavLink>
        <button
          onClick={logout}
          className={clsx(
            'flex w-full items-center rounded-lg text-sm font-medium text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
            collapsed ? 'h-9 justify-center px-0' : 'gap-2.5 px-2.5 py-1.5',
          )}
          title="Sign out"
        >
          <LogOut size={16} />
          {!collapsed && <span>Sign out</span>}
        </button>
      </div>
    </aside>
  )
}
