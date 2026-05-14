import { clsx } from 'clsx'
import type { ReactNode } from 'react'
import Card from './Card'

const accentToken = {
  brand:   { text: 'text-brand-600',   bg: 'bg-brand-50',   ring: 'ring-brand-100' },
  emerald: { text: 'text-emerald-600', bg: 'bg-emerald-50', ring: 'ring-emerald-100' },
  amber:   { text: 'text-amber-600',   bg: 'bg-amber-50',   ring: 'ring-amber-100' },
  rose:    { text: 'text-rose-600',    bg: 'bg-rose-50',    ring: 'ring-rose-100' },
  violet:  { text: 'text-violet-600',  bg: 'bg-violet-50',  ring: 'ring-violet-100' },
  slate:   { text: 'text-slate-600',   bg: 'bg-slate-100',  ring: 'ring-slate-200' },
} as const

export type StatAccent = keyof typeof accentToken

import type { LucideProps } from 'lucide-react'
import type { ForwardRefExoticComponent, RefAttributes } from 'react'

type LucideIcon = ForwardRefExoticComponent<Omit<LucideProps, 'ref'> & RefAttributes<SVGSVGElement>>

interface StatCardProps {
  label: string
  value: string | number
  icon?: LucideIcon | React.ComponentType<{ size?: number }>
  trend?: number
  accent?: StatAccent
  spark?: ReactNode
  hint?: string
}

export default function StatCard({ label, value, icon: IconComp, trend, accent = 'brand', spark, hint }: StatCardProps) {
  const a = accentToken[accent]
  return (
    <Card padding="md" className="relative overflow-hidden">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
          {label}
        </p>
        {IconComp && (
          <span className={clsx('inline-flex h-7 w-7 items-center justify-center rounded-lg', a.bg, a.text)}>
            <IconComp size={14} />
          </span>
        )}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="text-[26px] font-semibold tabular-nums tracking-tight text-slate-900 dark:text-white">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </span>
        {trend != null && (
          <span
            className={clsx(
              'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[11px] font-semibold',
              trend >= 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-rose-50 text-rose-600',
            )}
          >
            {trend >= 0 ? '+' : ''}{trend}%
          </span>
        )}
      </div>
      {hint && (
        <p className="mt-1 text-[12px] text-slate-400 dark:text-slate-500">{hint}</p>
      )}
      {spark && <div className="mt-3">{spark}</div>}
    </Card>
  )
}

/* ---------- SPARK BARS ---------- */
interface SparkBarsProps {
  data: number[]
  accent?: 'brand' | 'emerald' | 'amber' | 'rose' | 'violet'
  height?: number
}

const sparkColor = {
  brand: 'bg-brand-400',
  emerald: 'bg-emerald-400',
  amber: 'bg-amber-400',
  rose: 'bg-rose-400',
  violet: 'bg-violet-400',
}

export function SparkBars({ data, accent = 'brand', height = 32 }: SparkBarsProps) {
  const max = Math.max(1, ...data)
  const color = sparkColor[accent]
  return (
    <div className="flex items-end gap-[3px]" style={{ height }}>
      {data.map((v, i) => (
        <div
          key={i}
          className={clsx('flex-1 rounded-sm transition-all', color, v === 0 && 'opacity-30')}
          style={{ height: `${Math.max(8, (v / max) * 100)}%` }}
        />
      ))}
    </div>
  )
}
