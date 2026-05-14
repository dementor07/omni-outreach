import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Zap, AlertCircle, ChevronDown } from 'lucide-react'
import { clsx } from 'clsx'
import { api, apiBase } from '../api/client'
import Button from '../components/Button'
import Card from '../components/Card'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string })?.from || '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [showApi, setShowApi] = useState(false)

  // API health check
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [checking, setChecking] = useState(false)

  async function checkApi() {
    setChecking(true)
    try {
      const res = await fetch(`${apiBase}/health`)
      setApiOk(res.ok)
    } catch {
      setApiOk(false)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => { checkApi() }, [])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setErr(null)
    try {
      const res = await api.post('/auth/login', { email, password })
      localStorage.setItem('token', res.data.access_token)
      navigate(from, { replace: true })
    } catch (e2: unknown) {
      const msg = e2 instanceof Error ? e2.message : 'Login failed'
      setErr(
        msg.includes('Failed to fetch') || msg.includes('NetworkError') || msg.includes('Network Error')
          ? "Could not reach the backend. Check the API endpoint below — the dashboard must be served from an origin allowed by your backend's CORS."
          : msg.includes('401') ? 'Invalid email or password' : msg,
      )
    } finally {
      setSubmitting(false)
    }
  }

  const apiLabel = checking ? 'Checking…' : apiOk ? 'Backend reachable' : 'Backend unreachable'

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 py-8 dark:bg-[rgb(2,6,23)]">
      <div className="w-full max-w-sm">
        {/* Logo + heading */}
        <div className="mb-8 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-brand-500 text-white shadow-lg shadow-brand-500/30">
            <Zap size={22} fill="currentColor" />
          </div>
          <h1 className="mt-4 text-xl font-bold tracking-tight text-slate-900 dark:text-white">
            Sign in to Omni
          </h1>
          <p className="mt-1 text-[13px] text-slate-500">Control plane for outreach operations</p>
        </div>

        {/* Login card */}
        <Card padding="lg">
          <form onSubmit={onSubmit} className="space-y-4">
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="username"
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">
                Password
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="h-10 w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 outline-none transition-colors focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </div>
            {err && (
              <div className="flex items-start gap-2 rounded-lg border border-rose-100 bg-rose-50 px-3 py-2 text-[13px] text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
                <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
                <span>{err}</span>
              </div>
            )}
            <Button as="button" type="submit" variant="primary" size="md" className="w-full" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </Card>

        {/* API status */}
        <button
          onClick={() => setShowApi((v) => !v)}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 text-[12px] text-slate-500 transition-colors hover:text-slate-700"
        >
          <span className={clsx('h-2 w-2 rounded-full', apiOk ? 'bg-emerald-500' : 'bg-rose-500')} />
          <span>{apiLabel}</span>
          <span className="font-mono text-slate-400">{apiBase}</span>
          <ChevronDown size={11} className={clsx('transition-transform', showApi && 'rotate-180')} />
        </button>
      </div>
    </div>
  )
}
