import { clsx } from 'clsx'

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info' | 'muted'

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-slate-100 text-slate-700',
  success: 'bg-emerald-50 text-emerald-700',
  warning: 'bg-amber-50 text-amber-700',
  error:   'bg-rose-50 text-rose-700',
  info:    'bg-sky-50 text-sky-700',
  muted:   'bg-slate-100 text-slate-400',
}

const statusVariantMap: Record<string, BadgeVariant> = {
  active:   'success',
  queued:   'info',
  locked:   'warning',
  sent:     'success',
  failed:   'error',
  skipped:  'muted',
  stopped:  'muted',
  archived: 'muted',
  paused:   'warning',
  draft:    'default',
}

const channelVariantMap: Record<string, BadgeVariant> = {
  linkedin_invite: 'info',
  linkedin_dm:     'info',
  email:           'default',
  voice:           'success',
}

interface BadgeProps {
  label: string
  variant?: BadgeVariant
  asStatus?: boolean
  asChannel?: boolean
  className?: string
}

export default function Badge({ label, variant, asStatus, asChannel, className }: BadgeProps) {
  let resolved: BadgeVariant = variant ?? 'default'
  if (asStatus) resolved = statusVariantMap[label] ?? 'default'
  if (asChannel) resolved = channelVariantMap[label] ?? 'default'

  const display = label.replace(/_/g, ' ')

  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium capitalize',
        variantClasses[resolved],
        className,
      )}
    >
      {display}
    </span>
  )
}
