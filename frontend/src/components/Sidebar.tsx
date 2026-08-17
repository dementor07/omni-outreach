import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard, Megaphone, Inbox, ListTodo, UserCheck,
  Users, Building2, KanbanSquare, Contact,
  BarChart3, Activity, Sparkles,
  Plug, Database, FileText, ShieldOff, ShieldCheck, Settings, LogOut,
} from 'lucide-react'
import { clsx } from 'clsx'
import Logo, { LogoMark } from './Logo'

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
      { to: '/tones', label: 'Tones', icon: Sparkles },
      { to: '/blacklist', label: 'Blacklist', icon: ShieldOff },
      { to: '/deliverability', label: 'Deliverability', icon: ShieldCheck },
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
        'flex h-screen flex-col border-r border-slate-200/80 bg-white/90 shadow-[1px_0_0_rgb(255_255_255/0.7)] backdrop-blur-xl transition-[width] duration-200 dark:border-slate-800/80 dark:bg-slate-950/90 dark:shadow-none',
        collapsed ? 'w-16' : 'w-64',
      )}
    >
      {/* Logo lockup */}
      <div className={clsx('flex items-center border-b border-slate-100 px-4 py-4 dark:border-slate-800', collapsed && 'justify-center px-0')}>
        {collapsed ? <LogoMark size={30} /> : <Logo size={32} />}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-4 overflow-y-auto px-2.5 py-3">
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
                      'group relative flex w-full items-center rounded-lg text-sm font-medium transition-colors duration-150',
                      collapsed ? 'h-9 justify-center px-0' : 'gap-2.5 px-2.5 py-1.5',
                      isActive
                        ? 'bg-brand-50/90 text-slate-950 shadow-[inset_0_0_0_1px_rgb(254_205_211/0.45)] dark:bg-brand-950/35 dark:text-white dark:shadow-[inset_0_0_0_1px_rgb(136_19_55/0.4)]'
                        : 'text-slate-500 hover:bg-slate-100/70 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-white',
                    )
                  }
                  title={collapsed ? label : undefined}
                >
                  {({ isActive }) => (
                    <>
                      {/* One quiet brand cue: a thin accent rail on the active item. */}
                      {isActive && !collapsed && (
                        <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r-full bg-brand-500" />
                      )}
                      <Icon size={16} className={clsx('shrink-0', isActive ? 'text-brand-600 dark:text-brand-400' : '')} />
                      {!collapsed && <span className="flex-1 truncate text-left">{label}</span>}
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
              'flex w-full items-center rounded-lg text-sm font-medium transition-colors duration-150',
              collapsed ? 'h-9 justify-center px-0' : 'gap-2.5 px-2.5 py-1.5',
              isActive
                ? 'bg-slate-100 text-slate-900 dark:bg-slate-800/80 dark:text-white'
                : 'text-slate-500 hover:bg-slate-100/70 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/60 dark:hover:text-white',
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
