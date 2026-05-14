import { clsx } from 'clsx'
import type { LucideIcon } from 'lucide-react'

interface StatCardProps {
  label: string
  value: number | string
  icon?: LucideIcon
  trend?: number | { value: number; label: string }
  accent?: 'brand' | 'sky' | 'emerald' | 'amber' | 'rose' | 'violet' | 'slate'
  hint?: string
  loading?: boolean
}

const accentClasses = {
  brand:   'text-brand-600 bg-brand-50',
  sky:     'text-sky-600 bg-sky-50',
  emerald: 'text-emerald-600 bg-emerald-50',
  amber:   'text-amber-600 bg-amber-50',
  rose:    'text-rose-600 bg-rose-50',
  violet:  'text-violet-600 bg-violet-50',
  slate:   'text-slate-600 bg-slate-100',
} as const

export default function StatCard({ label, value, icon: Icon, trend, accent = 'brand', hint, loading }: StatCardProps) {
  const trendValue = typeof trend === 'number' ? trend : trend?.value
  const trendLabel = typeof trend === 'object' ? trend?.label : undefined

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-5 transition-colors dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
          {label}
        </p>
        {Icon && (
          <span className={clsx('inline-flex h-7 w-7 items-center justify-center rounded-lg', accentClasses[accent])}>
            <Icon size={14} />
          </span>
        )}
      </div>
      {loading ? (
        <div className="mt-3 h-7 w-24 skeleton" />
      ) : (
        <div className="mt-3 flex items-baseline gap-2">
          <span className="text-[26px] font-semibold tabular-nums tracking-tight text-slate-900 dark:text-white">
            {typeof value === 'number' ? value.toLocaleString() : value}
          </span>
          {trendValue != null && (
            <span
              className={clsx(
                'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold',
                trendValue >= 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600',
              )}
            >
              {trendValue >= 0 ? '+' : ''}{trendValue}%
              {trendLabel && <span className="ml-0.5 font-normal opacity-70">{trendLabel}</span>}
            </span>
          )}
        </div>
      )}
      {hint && !loading && (
        <p className="mt-1 text-[12px] text-slate-400 dark:text-slate-500">{hint}</p>
      )}
    </div>
  )
}
