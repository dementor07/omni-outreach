import { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LayoutDashboard, Moon, Sun, Search, Command, ChevronDown, Settings, LogOut, RefreshCw } from 'lucide-react'
import { clsx } from 'clsx'
import { useTheme } from '../hooks/useTheme'
import { apiBase, updateApiBase } from '../api/client'
import { auth } from '../api/v2'
import Button from './Button'
import Avatar from './Avatar'

/* ---------- ROUTE LABEL MAP (v2 CRM IA) ---------- */
const ROUTE_LABELS: Record<string, string> = {
  '/': 'Overview',
  '/contacts': 'Contacts',
  '/companies': 'Companies',
  '/deals': 'Deals',
  '/leads': 'Leads',
  '/campaigns': 'Campaigns',
  '/inbox': 'Inbox',
  '/tasks': 'Tasks',
  '/approvals': 'Approvals',
  '/analytics': 'Analytics',
  '/activity': 'Activity',
  '/ai-studio': 'AI Studio',
  '/integrations': 'Integrations',
  '/lead-sources': 'Lead Sources',
  '/templates': 'Templates',
  '/blacklist': 'Blacklist',
  '/settings': 'Settings',
}

interface TopbarProps {
  onToggleSidebar: () => void
}

export default function Topbar({ onToggleSidebar }: TopbarProps) {
  const { theme, toggle: toggleDark } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()

  // Derive route label from path
  const basePath = '/' + location.pathname.split('/').filter(Boolean)[0] || '/'
  const routeLabel = ROUTE_LABELS[basePath === '/' ? '/' : basePath] || 'Omni'

  // API status
  const [showApi, setShowApi] = useState(false)
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [checking, setChecking] = useState(false)
  const [draftBase, setDraftBase] = useState(apiBase)

  async function checkApi() {
    setChecking(true)
    try {
      // /auth/me with a valid token returns 200; with no/bad token returns 401.
      // Both prove the backend is up — only network failure is "offline".
      const token = localStorage.getItem('token')
      const res = await fetch(`${draftBase.replace(/\/$/, '')}/auth/me`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      setApiOk(res.status < 500)
    } catch {
      setApiOk(false)
    } finally {
      setChecking(false)
    }
  }

  function handleSave() {
    updateApiBase(draftBase)
    setShowApi(false)
    // Reload to ensure all queries pick up the new base URL
    window.location.reload()
  }

  // mount-only by design: re-running on every checkApi identity would re-ping the API each render
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { checkApi() }, [])

  const dot = apiOk ? 'bg-emerald-500' : apiOk === false ? 'bg-rose-500' : 'bg-slate-300'
  const label = checking ? 'Checking…' : apiOk ? 'API connected' : apiOk === false ? 'API offline' : 'No connection'

  // User menu — wired to the real signed-in user (was hardcoded "You").
  const meQ = useQuery({ queryKey: ['me'], queryFn: auth.me, staleTime: 5 * 60_000 })
  const userEmail = meQ.data?.email ?? ''
  const userName = userEmail ? userEmail.split('@')[0].replace(/[._-]+/g, ' ') : ''
  const [showUser, setShowUser] = useState(false)
  const userRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!showUser) return
    const h = (e: MouseEvent) => { if (userRef.current && !userRef.current.contains(e.target as Node)) setShowUser(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [showUser])

  function logout() {
    localStorage.removeItem('token')
    navigate('/login')
  }

  return (
    <div className="glass sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-slate-200/70 px-4 dark:border-slate-800/80">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" icon={LayoutDashboard} onClick={onToggleSidebar} aria-label="Toggle sidebar" />
        <span className="hidden text-sm font-medium text-slate-500 sm:inline dark:text-slate-400">
          Omni <span className="px-1.5 text-slate-300">/</span>
        </span>
        <span className="text-sm font-semibold text-slate-900 dark:text-white">{routeLabel}</span>
      </div>

      <div className="flex items-center gap-2">
        {/* Search shortcut */}
        <button className="hidden h-9 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 text-sm text-slate-400 transition-colors hover:bg-slate-100 md:inline-flex dark:border-slate-700 dark:bg-slate-900 dark:hover:bg-slate-800">
          <Search size={14} />
          Search
          <span className="ml-2 inline-flex items-center gap-0.5 rounded border border-slate-200 px-1 font-mono text-[10px] text-slate-400 dark:border-slate-700">
            <Command size={9} />K
          </span>
        </button>

        {/* API status pill */}
        <div className="relative">
          <button
            onClick={() => setShowApi((v) => !v)}
            className={clsx(
              'inline-flex h-9 items-center gap-2 rounded-lg border px-2.5 text-xs font-semibold transition-colors',
              apiOk
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'
                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300',
            )}
          >
            <span className={clsx('inline-block h-2 w-2 rounded-full', dot, apiOk && 'ring-pulse')} />
            <span className="hidden sm:inline">{label}</span>
            <ChevronDown size={11} className="opacity-60" />
          </button>
          {showApi && (
            <div className="glass-panel absolute right-0 top-11 z-50 w-80 rounded-2xl border border-white/40 p-3 dark:border-white/10">
              <p className="px-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">API base URL</p>
              <p className="mt-1 px-1 text-[12px] text-slate-500">
                Where this dashboard talks to your Omni backend.
              </p>
              <input
                type="text"
                value={draftBase}
                onChange={(e) => setDraftBase(e.target.value)}
                className="mt-2 h-9 w-full rounded-lg border border-slate-200 bg-white px-2.5 font-mono text-xs text-slate-700 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
              />
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className={clsx('text-[11px]', apiOk ? 'text-emerald-600' : 'text-slate-500')}>
                  {checking ? 'Pinging…' : apiOk ? 'Healthy ✓' : 'Not reachable'}
                </span>
                <div className="flex items-center gap-1.5">
                  <Button size="sm" variant="ghost" onClick={checkApi} icon={RefreshCw}>Test</Button>
                  <Button size="sm" variant="primary" onClick={handleSave} disabled={!apiOk}>Save</Button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Dark mode toggle */}
        <Button
          variant="ghost"
          size="sm"
          icon={theme === 'dark' ? Sun : Moon}
          onClick={toggleDark}
          aria-label="Toggle dark mode"
        />

        {/* User menu */}
        <div className="relative" ref={userRef}>
          <button onClick={() => setShowUser((v) => !v)} className="rounded-full transition-opacity hover:opacity-80" aria-label="Account menu">
            <Avatar name={userName || userEmail || '?'} size={28} />
          </button>
          {showUser && (
            <div className="glass-panel absolute right-0 top-11 z-50 w-56 overflow-hidden rounded-2xl border border-white/40 dark:border-white/10">
              <div className="border-b border-slate-100 px-3 py-2.5 dark:border-slate-800">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Signed in as</p>
                <p className="mt-0.5 truncate text-sm font-medium text-slate-900 dark:text-white" title={userEmail}>
                  {meQ.isLoading ? 'Loading…' : userEmail || 'Unknown user'}
                </p>
              </div>
              <div className="p-1">
                <button
                  onClick={() => { navigate('/settings'); setShowUser(false) }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
                >
                  <Settings size={14} />
                  Settings
                </button>
                <button
                  onClick={() => { logout(); setShowUser(false) }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-sm text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40"
                >
                  <LogOut size={14} />
                  Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
