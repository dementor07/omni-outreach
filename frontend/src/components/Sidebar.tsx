import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Megaphone, Inbox, ListTodo, UserCheck,
  Users, Building2, KanbanSquare, Contact,
  BarChart3, Activity, Sparkles,
  Plug, Database, FileText, ShieldOff, Settings, LogOut, Zap,
  ChevronRight,
} from 'lucide-react'
import { clsx } from 'clsx'

type NavItem = { to: string; label: string; icon: React.ElementType }
type NavGroup = { label: string | null; items: NavItem[] }

// CRM + outbound + AI information architecture (HubSpot/Salesforce/Apollo).
const NAV_GROUPS: NavGroup[] = [
  {
    label: null,
    items: [
      { to: '/', label: 'Overview', icon: LayoutDashboard },
    ],
  },
  {
    label: 'CRM',
    items: [
      { to: '/contacts', label: 'Contacts', icon: Contact },
      { to: '/companies', label: 'Companies', icon: Building2 },
      { to: '/deals', label: 'Deals', icon: KanbanSquare },
      { to: '/leads', label: 'Leads', icon: Users },
    ],
  },
  {
    label: 'Engage',
    items: [
      { to: '/campaigns', label: 'Campaigns', icon: Megaphone },
      { to: '/inbox', label: 'Inbox', icon: Inbox },
      { to: '/tasks', label: 'Tasks', icon: ListTodo },
      { to: '/approvals', label: 'Approvals', icon: UserCheck },
    ],
  },
  {
    label: 'Intelligence',
    items: [
      { to: '/analytics', label: 'Analytics', icon: BarChart3 },
      { to: '/activity', label: 'Activity', icon: Activity },
      { to: '/ai-studio', label: 'AI Studio', icon: Sparkles },
    ],
  },
  {
    label: 'Setup',
    items: [
      { to: '/integrations', label: 'Integrations', icon: Plug },
      { to: '/lead-sources', label: 'Lead Sources', icon: Database },
      { to: '/templates', label: 'Templates', icon: FileText },
      { to: '/blacklist', label: 'Blacklist', icon: ShieldOff },
    ],
  },
]

interface SidebarProps {
  collapsed?: boolean
}

export default function Sidebar({ collapsed = false }: SidebarProps) {
  const navigate = useNavigate()

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
              {group.items.map(({ to, label, icon: Icon }) => (
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
                      {isActive && !collapsed && <ChevronRight size={12} className="text-brand-400" />}
                    </>
                  )}
                </NavLink>
              ))}
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
          type="button"
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
