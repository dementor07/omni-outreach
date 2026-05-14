import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
  padding?: 'none' | 'sm' | 'md' | 'lg'
}

const paddingClass = {
  none: '',
  sm: 'p-4',
  md: 'p-5',
  lg: 'p-6',
} as const

export function Card({ children, className = '', padding = 'md' }: CardProps) {
  return (
    <div
      className={clsx(
        'rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900',
        paddingClass[padding],
        className,
      )}
    >
      {children}
    </div>
  )
}

interface CardHeaderProps {
  title: string
  description?: string
  actions?: ReactNode
  className?: string
}

export function CardHeader({ title, description, actions, className = '' }: CardHeaderProps) {
  return (
    <div className={clsx('mb-4 flex items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-slate-900 dark:text-white">{title}</h2>
        {description && (
          <p className="mt-0.5 text-[13px] text-slate-500 dark:text-slate-400">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-shrink-0 items-center gap-1.5">{actions}</div>}
    </div>
  )
}
