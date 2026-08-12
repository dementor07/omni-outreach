import { FormEvent, useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { workspaces } from '../api/v2'
import Button from '../components/Button'
import { LogoMark } from '../components/Logo'

type Status = 'working' | 'ok' | 'error' | 'need_login' | 'need_register'

interface InviteInfo {
  email?: string
  role?: string
  workspace_name?: string
}

/**
 * Redeem a workspace invite from the email link (/invite?token=...).
 * - Logged in                → accept immediately.
 * - Logged out, has account  → sign in (then this page runs again and accepts).
 * - Logged out, no account   → create an account with the INVITED email + join
 *                              the workspace with the invited role, in one step.
 * On success we swap in the returned workspace-scoped JWT and hard-reload so the
 * whole app re-initialises inside the joined workspace.
 */
export default function InviteAccept() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [status, setStatus] = useState<Status>('working')
  const [message, setMessage] = useState('')
  const [info, setInfo] = useState<InviteInfo>({})
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const ran = useRef(false)

  const enterWorkspace = (accessToken: string) => {
    localStorage.setItem('token', accessToken)
    setStatus('ok')
    setTimeout(() => {
      window.location.href = '/'
    }, 900)
  }

  const detail = (err: unknown, fallback: string) =>
    (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? fallback

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    if (!token) {
      setStatus('error')
      setMessage('This invitation link is missing its token.')
      return
    }
    // Already signed in → accept straight away.
    if (localStorage.getItem('token')) {
      workspaces
        .acceptInvite(token)
        .then((res) => enterWorkspace(res.access_token))
        .catch((err) => {
          setStatus('error')
          setMessage(detail(err, 'This invitation could not be accepted — it may have expired or been revoked.'))
        })
      return
    }
    // Not signed in → look up the invite to decide sign-in vs create-account.
    workspaces
      .inviteInfo(token)
      .then((res) => {
        if (!res.valid) {
          setStatus('error')
          setMessage(
            res.reason === 'expired'
              ? 'This invitation has expired. Ask for a fresh invite.'
              : res.reason === 'already_accepted'
                ? 'This invitation has already been accepted. Try signing in.'
                : 'This invitation is no longer valid.',
          )
          return
        }
        setInfo({ email: res.email, role: res.role, workspace_name: res.workspace_name })
        setStatus(res.has_account ? 'need_login' : 'need_register')
      })
      .catch((err) => {
        setStatus('error')
        setMessage(detail(err, 'This invitation could not be loaded.'))
      })
  }, [token])

  const goLogin = () => navigate('/login', { replace: true, state: { from: `/invite?token=${token}` } })

  async function onRegister(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setMessage('')
    setSubmitting(true)
    try {
      const res = await workspaces.registerAccept(token, password)
      enterWorkspace(res.access_token)
    } catch (err) {
      setMessage(detail(err, 'Could not create your account. The invite may have expired.'))
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4 dark:bg-slate-950">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3">
          <LogoMark size={44} className="shadow-lg" />
          <h1 className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">Workspace invitation</h1>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
          {status === 'working' && <p className="text-center text-sm text-slate-500">Loading your invitation…</p>}

          {status === 'ok' && (
            <p className="text-center text-sm font-medium text-emerald-600">You're in. Taking you to the workspace…</p>
          )}

          {status === 'need_login' && (
            <div className="space-y-4 text-center">
              <p className="text-sm text-slate-600 dark:text-slate-300">
                You already have an account for <b>{info.email}</b>. Sign in and the invite to{' '}
                <b>{info.workspace_name}</b> will be applied automatically.
              </p>
              <Button variant="primary" className="w-full" onClick={goLogin}>
                Sign in to accept
              </Button>
            </div>
          )}

          {status === 'need_register' && (
            <form onSubmit={onRegister} className="space-y-4">
              <p className="text-sm text-slate-600 dark:text-slate-300">
                You've been invited to join <b>{info.workspace_name}</b> as <b>{info.role}</b>. Create your account to continue.
              </p>
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Email</span>
                <input
                  type="email"
                  value={info.email ?? ''}
                  readOnly
                  className="mt-1 w-full cursor-not-allowed rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800"
                />
              </label>
              <label className="block">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Create a password</span>
                <input
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                />
              </label>
              {message && <p className="rounded-md bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">{message}</p>}
              <Button type="submit" variant="primary" isLoading={submitting} className="w-full">
                Create account & join
              </Button>
            </form>
          )}

          {status === 'error' && (
            <div className="space-y-4 text-center">
              <p className="rounded-md bg-rose-50 px-3 py-2 text-xs font-medium text-rose-700">{message}</p>
              <Button variant="secondary" className="w-full" onClick={() => navigate('/login', { replace: true })}>
                Go to sign in
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
