import { clsx } from 'clsx'
import type { ElementType, ButtonHTMLAttributes, ReactNode } from 'react'

const sizeClasses = {
  xs: 'h-7 px-2.5 text-xs gap-1.5',
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9 px-3.5 text-sm gap-2',
} as const

const variantClasses = {
  // Solid, deep brand fill with a restrained soft shadow. Confident, not loud —
  // no gradient or glow on a button that recurs across every screen.
  primary:
    'border border-brand-700/20 bg-brand-600 text-white shadow-soft hover:-translate-y-px hover:bg-brand-700 hover:shadow-card disabled:opacity-50',
  secondary:
    'bg-white text-slate-700 border border-slate-200 shadow-soft hover:bg-slate-50 hover:text-slate-900 hover:border-slate-300 dark:bg-slate-900 dark:text-slate-200 dark:border-slate-700 dark:hover:bg-slate-800',
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

// Icons here are decorative — the button's own text (or its aria-label) is the
// accessible name — so the component needs to be able to pass aria-hidden down.
// Without it in the signature a custom icon component silently drops the
// attribute and screen readers announce the glyph on top of the label.
type ButtonIcon =
  | LucideIcon
  | React.ComponentType<{ size?: number; className?: string; 'aria-hidden'?: boolean | 'true' | 'false' }>

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  as?: ElementType
  size?: ButtonSize
  variant?: ButtonVariant
  icon?: ButtonIcon
  iconRight?: ButtonIcon
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
        // The transition names its properties. `transition-all` was animating
        // every animatable property including layout ones, which is both a
        // paint cost on a component this common and a source of odd flicker
        // when a variant swaps padding or width.
        'inline-flex shrink-0 items-center justify-center rounded-lg font-semibold',
        'transition-[color,background-color,border-color,box-shadow,transform] duration-150 active:scale-[0.97]',
        // A keyboard user had no idea where they were: nothing in the base or
        // variant classes drew a focus state, so the only indicator was the
        // browser default outline — which the surrounding inputs suppress with
        // outline-none, making focus inconsistent across a single form. The
        // offset ring reads on both the light page and the dark chrome.
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-900',
        sizeClasses[size],
        variantClasses[variant],
        isDisabled && 'pointer-events-none opacity-60',
        className,
      )}
      disabled={isDisabled}
      aria-busy={isLoading || undefined}
      {...rest}
    >
      {isLoading ? <Spinner size={iconSize} /> : IconComp && <IconComp size={iconSize} aria-hidden="true" />}
      {children}
      {!isLoading && IconR && <IconR size={iconSize} aria-hidden="true" />}
    </Comp>
  )
}
