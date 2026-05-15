import { clsx } from 'clsx'
import type { ReactNode } from 'react'

const badgeVariant = {
  neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  brand: 'bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-300',
  success: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  warning: 'bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  danger: 'bg-rose-50 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
  info: 'bg-sky-50 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  violet: 'bg-violet-50 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300',
} as const

const statusVariant: Record<string, keyof typeof badgeVariant> = {
  queued: 'neutral', locked: 'warning', sent: 'success', failed: 'danger', skipped: 'neutral',
  active: 'success', paused: 'warning', archived: 'neutral', live: 'success', simulation: 'warning',
  positive: 'success', negative: 'danger', neutral: 'neutral',
  pending: 'warning', approved: 'success', rejected: 'danger',
  replied: 'brand', stopped: 'danger',
}

const channelVariant: Record<string, keyof typeof badgeVariant> = {
  email: 'info', linkedin_dm: 'brand', linkedin_invite: 'brand', linkedin_inmail: 'brand',
  linkedin: 'brand', whatsapp: 'success', sms: 'violet', voice: 'violet',
}

const dotColor: Record<string, string> = {
  success: 'bg-emerald-500', warning: 'bg-amber-500', danger: 'bg-rose-500',
  info: 'bg-sky-500', brand: 'bg-brand-500', violet: 'bg-violet-500', neutral: 'bg-slate-400',
}

export type BadgeVariant = keyof typeof badgeVariant

export type BadgeSize = 'xs' | 'sm' | 'md'

const sizeClasses: Record<BadgeSize, string> = {
  xs: 'px-1.5 py-0 text-[10px]',
  sm: 'px-2 py-0.5 text-[11px]',
  md: 'px-2.5 py-0.5 text-xs',
}

interface BadgeProps {
  label: string
  variant?: BadgeVariant
  asStatus?: boolean
  asChannel?: boolean
  dot?: boolean
  size?: BadgeSize
  icon?: React.ComponentType<{ size?: number }>
  className?: string
  children?: ReactNode
}

export default function Badge({
  label,
  variant,
  asStatus,
  asChannel,
  dot,
  size = 'sm',
  icon: IconComp,
  className = '',
}: BadgeProps) {
  let v: BadgeVariant = variant || 'neutral'
  let text = label
  if (asStatus) v = statusVariant[label] || 'neutral'
  if (asChannel) {
    v = channelVariant[label] || 'neutral'
    text = label.replace(/_/g, ' ')
  }
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-md font-medium capitalize',
        sizeClasses[size],
        badgeVariant[v],
        className,
      )}
    >
      {dot && <span className={clsx('h-1.5 w-1.5 rounded-full', dotColor[v])} />}
      {IconComp && <IconComp size={11} />}
      {text}
    </span>
  )
}
