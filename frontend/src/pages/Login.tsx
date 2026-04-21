import { FormEvent, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ArrowRight, Shield } from 'lucide-react'
import axios from 'axios'

import { api } from '../api/client'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError('')

    try {
      const { data } = await api.post<{ access_token: string }>('/auth/login', { email, password })
      localStorage.setItem('token', data.access_token)
      const destination = (location.state as { from?: string } | null)?.from || '/'
      navigate(destination, { replace: true })
    } catch (err) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || 'Login failed')
      } else {
        setError('Login failed')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="mx-auto flex min-h-screen max-w-6xl items-center justify-center px-6 py-16">
        <div className="grid w-full max-w-5xl overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-2xl lg:grid-cols-[1.05fr_0.95fr]">
          <div className="relative hidden min-h-[620px] overflow-hidden bg-sky-500 p-12 text-white lg:block">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,255,255,0.22),transparent_35%),radial-gradient(circle_at_bottom_right,rgba(14,165,233,0.35),transparent_50%)]" />
            <div className="relative z-10 flex h-full flex-col justify-between">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em]">
                  <Shield size={14} />
                  Omni Outreach
                </div>
                <h1 className="mt-8 max-w-md text-4xl font-semibold tracking-tight">
                  Multi-channel outreach, operated from one calm control surface.
                </h1>
                <p className="mt-4 max-w-md text-sm leading-7 text-sky-50/90">
                  LinkedIn, email, queue health, campaign pacing, and live operations in one place.
                </p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-2xl border border-white/15 bg-white/10 p-5 backdrop-blur-sm">
                  <p className="text-2xl font-semibold">Queue-first</p>
                  <p className="mt-2 text-sm text-sky-50/80">Dispatch, retries, and state are visible instead of buried.</p>
                </div>
                <div className="rounded-2xl border border-white/15 bg-white/10 p-5 backdrop-blur-sm">
                  <p className="text-2xl font-semibold">Operator-safe</p>
                  <p className="mt-2 text-sm text-sky-50/80">Clean workflows for campaigns, leads, and accounts.</p>
                </div>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-center px-8 py-12 sm:px-12">
            <div className="w-full max-w-md">
              <div className="mb-8">
                <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Omni Outreach Admin</p>
                <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Welcome back</h2>
                <p className="mt-2 text-sm leading-6 text-slate-500">
                  Sign in to manage campaigns, inspect leads, and keep the queue moving.
                </p>
              </div>

              <form className="space-y-5" onSubmit={handleSubmit}>
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">Email</span>
                  <input
                    type="email"
                    value={email}
                    onChange={(event) => setEmail(event.target.value)}
                    className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                    placeholder="you@company.com"
                    required
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">Password</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="w-full rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100"
                    placeholder="Enter your password"
                    required
                  />
                </label>

                {error && (
                  <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-sky-500 px-4 py-3 text-sm font-semibold text-white transition hover:bg-sky-600 disabled:cursor-not-allowed disabled:bg-sky-300"
                >
                  {loading ? 'Signing in...' : 'Sign in'}
                  {!loading && <ArrowRight size={16} />}
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
