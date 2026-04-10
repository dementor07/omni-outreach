import { clsx } from 'clsx'
import type { LucideIcon } from 'lucide-react'

interface StatCardProps {
  label: string
  value: number | string
  icon?: LucideIcon
  trend?: { value: number; label: string }
  accent?: 'sky' | 'emerald' | 'amber' | 'rose'
  loading?: boolean
}

const accentClasses = {
  sky:     'text-sky-600 bg-sky-50',
  emerald: 'text-emerald-600 bg-emerald-50',
  amber:   'text-amber-600 bg-amber-50',
  rose:    'text-rose-600 bg-rose-50',
}

export default function StatCard({ label, value, icon: Icon, trend, accent = 'sky', loading }: StatCardProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        {Icon && (
          <span className={clsx('p-2 rounded-md', accentClasses[accent])}>
            <Icon size={16} />
          </span>
        )}
      </div>
      {loading ? (
        <div className="mt-2 h-8 w-24 skeleton" />
      ) : (
        <p className="mt-2 text-2xl font-semibold text-slate-900 tabular-nums">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </p>
      )}
      {trend && !loading && (
        <p className={clsx('mt-1 text-xs', trend.value >= 0 ? 'text-emerald-600' : 'text-rose-600')}>
          {trend.value >= 0 ? '+' : ''}{trend.value}% {trend.label}
        </p>
      )}
    </div>
  )
}
