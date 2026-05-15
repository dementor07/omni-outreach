import { clsx } from 'clsx'
import type { ElementType, ButtonHTMLAttributes, ReactNode } from 'react'

const sizeClasses = {
  xs: 'h-7 px-2.5 text-xs gap-1.5',
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-3.5 text-sm gap-2',
} as const

const variantClasses = {
  primary:
    'bg-brand-500 text-white shadow-sm shadow-brand-500/20 hover:bg-brand-600 disabled:opacity-50',
  secondary:
    'bg-white text-slate-700 border border-slate-200 shadow-sm hover:bg-slate-50 hover:text-slate-900 dark:bg-slate-900 dark:text-slate-200 dark:border-slate-700 dark:hover:bg-slate-800',
  ghost:
    'text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white',
  danger:
    'bg-rose-50 text-rose-600 border border-rose-100 hover:bg-rose-100 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900',
} as const

export type ButtonSize = keyof typeof sizeClasses
export type ButtonVariant = keyof typeof variantClasses

import type { LucideProps } from 'lucide-react'
import type { ForwardRefExoticComponent, RefAttributes } from 'react'

type LucideIcon = ForwardRefExoticComponent<Omit<LucideProps, 'ref'> & RefAttributes<SVGSVGElement>>

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  as?: ElementType
  size?: ButtonSize
  variant?: ButtonVariant
  icon?: LucideIcon | React.ComponentType<{ size?: number; className?: string }>
  iconRight?: LucideIcon | React.ComponentType<{ size?: number; className?: string }>
  isLoading?: boolean
  children?: ReactNode
}

function Spinner({ size }: { size: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className="animate-spin"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path
        d="M22 12a10 10 0 0 1-10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

export default function Button({
  as: Comp = 'button',
  size = 'md',
  variant = 'secondary',
  icon: IconComp,
  iconRight: IconR,
  isLoading,
  disabled,
  children,
  className = '',
  ...rest
}: ButtonProps) {
  const iconSize = size === 'md' ? 15 : 13
  const isDisabled = disabled || isLoading
  return (
    <Comp
      className={clsx(
        'inline-flex items-center justify-center rounded-lg font-semibold transition-colors active:scale-[0.98]',
        sizeClasses[size],
        variantClasses[variant],
        isDisabled && 'opacity-60 pointer-events-none',
        className,
      )}
      disabled={isDisabled}
      {...rest}
    >
      {isLoading ? <Spinner size={iconSize} /> : IconComp && <IconComp size={iconSize} />}
      {children}
      {!isLoading && IconR && <IconR size={iconSize} />}
    </Comp>
  )
}
