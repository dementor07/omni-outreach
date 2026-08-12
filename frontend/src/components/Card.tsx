import { clsx } from 'clsx'
import type { ElementType, HTMLAttributes, ReactNode } from 'react'

interface CardProps extends HTMLAttributes<HTMLElement> {
  as?: ElementType
  padding?: 'none' | 'sm' | 'md' | 'lg'
  /** Soft layered elevation. Default true — gives cards real depth over the
   *  gradient-mesh background instead of a flat hairline. Set false for nested
   *  / inset cards that shouldn't float. */
  elevated?: boolean
  /** Clickable lift on hover (use for cards that navigate). */
  hover?: boolean
  /** Translucent blurred surface for floating chrome. */
  glass?: boolean
  children?: ReactNode
}

export default function Card({
  as: Tag = 'div',
  className = '',
  padding = 'md',
  elevated = true,
  hover = false,
  glass = false,
  children,
  ...rest
}: CardProps) {
  return (
    <Tag
      className={clsx(
        'min-w-0 rounded-2xl border',
        'transition-colors',
        glass
          ? 'glass-panel border-white/40 dark:border-white/10'
          : 'border-slate-200/75 bg-white/95 dark:border-slate-800 dark:bg-slate-900/90',
        elevated && !glass && 'shadow-card',
        hover && 'lift cursor-pointer',
        padding === 'sm' && 'p-3.5 sm:p-4',
        padding === 'md' && 'p-4 sm:p-5',
        padding === 'lg' && 'p-4 sm:p-6',
        className,
      )}
      {...rest}
    >
      {children}
    </Tag>
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
