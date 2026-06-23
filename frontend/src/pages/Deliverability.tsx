import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, BadgeCheck, CircleHelp, MailCheck, ServerCog, ShieldCheck, ShieldX } from 'lucide-react'
import {
  deliverability,
  type EmailVerification,
  type EmailVerificationStatus,
  type SenderHealth,
  type VerificationProviderHealth,
} from '../api/v2'
import Badge, { type BadgeVariant } from '../components/Badge'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import { useToast } from '../components/Toast'

const inputClass =
  'h-10 min-w-[240px] flex-1 rounded-lg border border-slate-200 bg-white px-3 text-sm shadow-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white'

const STATUS_META: Record<
  EmailVerificationStatus,
  { label: string; variant: BadgeVariant; explanation: string }
> = {
  verified: {
    label: 'Verified',
    variant: 'success',
    explanation: 'Mailbox-level evidence from a trusted verification provider.',
  },
  valid_domain: {
    label: 'Domain valid',
    variant: 'info',
    explanation: 'Syntax and MX pass. This does not prove the mailbox exists.',
  },
  risky: {
    label: 'Risky',
    variant: 'warning',
    explanation: 'Deliverable domain with a risk signal such as a role address.',
  },
  invalid: {
    label: 'Invalid',
    variant: 'danger',
    explanation: 'Invalid syntax, disposable domain, or no receiving mail server.',
  },
  unknown: {
    label: 'Unknown',
    variant: 'neutral',
    explanation: 'The check could not establish enough evidence.',
  },
}

const REASON_LABELS: Record<string, string> = {
  invalid_syntax: 'Invalid email syntax',
  disposable_domain: 'Disposable email domain',
  no_mx: 'Domain has no MX record',
  dns_unavailable: 'DNS lookup unavailable',
  role_based: 'Role-based address',
  mx_present_mailbox_unverified: 'MX present; mailbox unverified',
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function Metric({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string
  value: number
  icon: typeof ShieldCheck
  tone: string
}) {
  return (
    <Card padding="sm" elevated={false}>
      <div className="flex items-center gap-3">
        <span className={`flex h-9 w-9 items-center justify-center rounded-xl ${tone}`}>
          <Icon size={17} />
        </span>
        <div>
          <p className="text-xl font-semibold tracking-tight text-slate-900 dark:text-white">{value}</p>
          <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
        </div>
      </div>
    </Card>
  )
}

export default function Deliverability() {
  const [email, setEmail] = useState('')
  const qc = useQueryClient()
  const toast = useToast()
  const summaryQ = useQuery({ queryKey: ['deliverability', 'summary'], queryFn: deliverability.summary })
  const checksQ = useQuery({ queryKey: ['deliverability', 'verifications'], queryFn: () => deliverability.list() })
  const providersQ = useQuery({ queryKey: ['deliverability', 'providers'], queryFn: deliverability.providers })
  const sendersQ = useQuery({ queryKey: ['deliverability', 'senders'], queryFn: deliverability.senderHealth })
  const verifyMut = useMutation({
    mutationFn: () => deliverability.verify(email.trim()),
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['deliverability'] })
      setEmail('')
      toast.success(`${result.email_normalized}: ${STATUS_META[result.status].label}`)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not verify email'),
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (email.trim()) verifyMut.mutate()
  }

  const summary = summaryQ.data
  const checks = checksQ.data ?? []
  const providers = providersQ.data ?? []
  const senders = sendersQ.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Deliverability"
        eyebrow="Setup"
        title="Deliverability"
        description="Inspect the evidence used to protect outbound email. Omni distinguishes mailbox verification from syntax and MX evidence, so weak checks never masquerade as certainty."
      />

      <Card>
        <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-[280px] flex-1 flex-col gap-1.5 text-xs font-medium text-slate-500">
            Check an email
            <input
              type="text"
              inputMode="email"
              aria-label="Email to verify"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="person@company.com"
              className={inputClass}
            />
          </label>
          <Button type="submit" variant="primary" icon={MailCheck} isLoading={verifyMut.isPending} disabled={!email.trim()}>
            Verify
          </Button>
        </form>
        <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
          DNS checks prove whether a domain accepts email. Only provider-backed mailbox evidence receives the
          <span className="font-semibold text-emerald-600 dark:text-emerald-400"> Verified</span> label.
        </p>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Metric label="Mailbox verified" value={summary?.verified ?? 0} icon={BadgeCheck} tone="bg-emerald-50 text-emerald-600 dark:bg-emerald-950/40" />
        <Metric label="Domain valid" value={summary?.valid_domain ?? 0} icon={ShieldCheck} tone="bg-sky-50 text-sky-600 dark:bg-sky-950/40" />
        <Metric label="Risky" value={summary?.risky ?? 0} icon={AlertTriangle} tone="bg-amber-50 text-amber-600 dark:bg-amber-950/40" />
        <Metric label="Invalid" value={summary?.invalid ?? 0} icon={ShieldX} tone="bg-rose-50 text-rose-600 dark:bg-rose-950/40" />
        <Metric label="Unknown / expired" value={(summary?.unknown ?? 0) + (summary?.expired ?? 0)} icon={CircleHelp} tone="bg-slate-100 text-slate-500 dark:bg-slate-800" />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Verification waterfall</h2>
              <p className="mt-1 text-xs text-slate-500">Ordered providers with automatic failure isolation.</p>
            </div>
            <ServerCog size={18} className="text-slate-400" />
          </div>
          {providers.length === 0 ? (
            <p className="rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-500 dark:bg-slate-800/50">
              No external verifier configured. Add a Hunter or ZeroBounce integration; local syntax and MX checks remain active.
            </p>
          ) : (
            <div className="space-y-2">
              {providers.map((provider: VerificationProviderHealth) => {
                const circuitOpen = Boolean(provider.open_until && new Date(provider.open_until).getTime() > Date.now())
                return (
                  <div key={provider.connection_id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
                    <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-xs font-bold text-brand-600 dark:bg-brand-950/40">
                      {provider.priority}
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{provider.connection_name}</p>
                      <p className="text-xs capitalize text-slate-400">
                        {provider.provider} · {provider.last_latency_ms == null ? 'not checked' : `${provider.last_latency_ms} ms`}
                      </p>
                    </div>
                    <Badge
                      label={circuitOpen ? 'Circuit open' : provider.consecutive_failures ? 'Degraded' : 'Ready'}
                      variant={circuitOpen ? 'danger' : provider.consecutive_failures ? 'warning' : 'success'}
                      size="xs"
                    />
                  </div>
                )
              })}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Sender transport health</h2>
              <p className="mt-1 text-xs text-slate-500">Seven-day SMTP outcomes—not an inbox-placement claim.</p>
            </div>
            <MailCheck size={18} className="text-slate-400" />
          </div>
          {senders.length === 0 ? (
            <p className="rounded-xl bg-slate-50 p-4 text-xs leading-5 text-slate-500 dark:bg-slate-800/50">
              No email sending accounts are configured yet.
            </p>
          ) : (
            <div className="space-y-2">
              {senders.map((sender: SenderHealth) => {
                const variant: BadgeVariant =
                  sender.health_status === 'healthy' ? 'success'
                    : sender.health_status === 'warning' ? 'warning'
                      : sender.health_status === 'critical' ? 'danger' : 'neutral'
                return (
                  <div key={sender.sending_account_id} className="flex items-center gap-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-slate-900 dark:text-white">{sender.identity}</p>
                      <p className="text-xs text-slate-400">
                        {sender.sent_7d} sent · {sender.transient_failures_7d} transient · {sender.permanent_failures_7d} permanent
                      </p>
                    </div>
                    <Badge label={sender.health_status} variant={variant} size="xs" />
                  </div>
                )
              })}
            </div>
          )}
        </Card>
      </div>

      <Card padding={checks.length ? 'none' : 'lg'}>
        {checksQ.isLoading ? (
          <p className="p-5 text-sm text-slate-500">Loading verification evidence…</p>
        ) : checks.length === 0 ? (
          <EmptyState
            icon={MailCheck}
            title="No email checks yet"
            description="Verify an address above or add the Email Verify node before an outbound email step."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="border-b border-slate-100 bg-slate-50/70 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-400 dark:border-slate-800 dark:bg-slate-900">
                <tr>
                  <th className="px-5 py-3">Email</th>
                  <th className="px-5 py-3">Evidence</th>
                  <th className="px-5 py-3">Reason</th>
                  <th className="px-5 py-3">Provider</th>
                  <th className="px-5 py-3">Checked</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {checks.map((check: EmailVerification) => {
                  const meta = STATUS_META[check.status]
                  const expired = new Date(check.expires_at).getTime() <= Date.now()
                  return (
                    <tr key={check.email_normalized} className="text-sm">
                      <td className="px-5 py-3.5">
                        <p className="font-medium text-slate-900 dark:text-white">{check.email_normalized}</p>
                        {check.mx_domain && <p className="mt-0.5 text-xs text-slate-400">{check.mx_domain}</p>}
                      </td>
                      <td className="px-5 py-3.5">
                        <div className="flex items-center gap-2">
                          <Badge label={meta.label} variant={meta.variant} size="xs" />
                          {expired && <Badge label="Expired" variant="neutral" size="xs" />}
                        </div>
                        <p className="mt-1 max-w-xs text-xs text-slate-400">{meta.explanation}</p>
                      </td>
                      <td className="px-5 py-3.5 text-slate-600 dark:text-slate-300">
                        {REASON_LABELS[check.reason] ?? check.reason.replace(/_/g, ' ')}
                      </td>
                      <td className="px-5 py-3.5 font-mono text-xs text-slate-500">{check.provider}</td>
                      <td className="whitespace-nowrap px-5 py-3.5 text-xs text-slate-500">{formatDate(check.checked_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
