import { clsx } from 'clsx'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

type ButtonSize = 'xs' | 'sm' | 'md'
type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  size?: ButtonSize
  variant?: ButtonVariant
  icon?: LucideIcon
  iconRight?: LucideIcon
  children?: ReactNode
}

const sizeClass = {
  xs: 'h-7 px-2.5 text-xs gap-1.5',
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-3.5 text-sm gap-2',
} as const

const variantClass = {
  primary:
    'bg-brand-500 text-white shadow-sm shadow-brand-500/20 hover:bg-brand-600 disabled:opacity-50',
  secondary:
    'bg-white text-slate-700 border border-slate-200 shadow-sm hover:bg-slate-50 hover:text-slate-900 dark:bg-slate-900 dark:text-slate-200 dark:border-slate-700 dark:hover:bg-slate-800',
  ghost:
    'text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
  danger:
    'bg-rose-50 text-rose-600 border border-rose-100 hover:bg-rose-100 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900',
} as const

export default function Button({
  size = 'md',
  variant = 'secondary',
  icon: Icon,
  iconRight: IconRight,
  children,
  className = '',
  ...rest
}: ButtonProps) {
  const iconSize = size === 'md' ? 15 : 13
  return (
    <button
      className={clsx(
        'inline-flex items-center justify-center rounded-lg font-semibold transition-colors active:scale-[0.98]',
        sizeClass[size],
        variantClass[variant],
        className,
      )}
      {...rest}
    >
      {Icon && <Icon size={iconSize} />}
      {children}
      {IconRight && <IconRight size={iconSize} />}
    </button>
  )
}
