import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Megaphone, Users, ListTodo, Settings, LogOut, Zap, Search, Database } from 'lucide-react'
import { clsx } from 'clsx'

const navItems = [
  { to: '/',              label: 'Overview',      icon: LayoutDashboard },
  { to: '/campaigns',    label: 'Campaigns',     icon: Megaphone },
  { to: '/leads',        label: 'Leads',         icon: Users },
  { to: '/queue',        label: 'Queue',         icon: ListTodo },
  { to: '/lead-sources', label: 'Lead Sources',  icon: Database },
  { to: '/job-search',   label: 'Job Search',    icon: Search },
  { to: '/settings',     label: 'Settings',      icon: Settings },
]

export default function Sidebar() {
  const navigate = useNavigate()

  function logout() {
    localStorage.removeItem('token')
    navigate('/login')
  }

  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-white border-r border-slate-200 flex flex-col z-30">
      {/* Logo */}
      <div className="flex items-center gap-2.5 px-5 py-5 border-b border-slate-100">
        <div className="flex items-center justify-center w-7 h-7 bg-sky-500 rounded-lg">
          <Zap size={14} className="text-white" fill="white" />
        </div>
        <div>
          <span className="block text-sm font-bold tracking-tight text-slate-900">Omni</span>
          <span className="block text-[11px] uppercase tracking-[0.18em] text-slate-400">Control Plane</span>
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
                  ? 'bg-sky-50 text-sky-600'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900',
              )
            }
          >
            <Icon size={16} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-3 py-4 border-t border-slate-100">
        <button
          onClick={logout}
          className="flex items-center gap-3 w-full px-3 py-2 rounded-md text-sm font-medium text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition-colors"
        >
          <LogOut size={16} />
          Sign out
        </button>
      </div>
    </aside>
  )
}
