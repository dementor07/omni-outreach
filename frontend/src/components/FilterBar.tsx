import { clsx } from 'clsx'
import { Search, X, ChevronDown } from 'lucide-react'
import type { ReactNode } from 'react'

/* ---------- FILTER BAR ---------- */
interface FilterBarProps {
  children: ReactNode
  className?: string
}

export function FilterBar({ children, className = '' }: FilterBarProps) {
  return (
    <div
      className={clsx(
        'flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200 bg-white p-2 dark:border-slate-800 dark:bg-slate-900',
        className,
      )}
    >
      {children}
    </div>
  )
}

/* ---------- SEARCH INPUT ---------- */
interface SearchInputProps {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}

export function SearchInput({ value, onChange, placeholder = 'Search…', className = '' }: SearchInputProps) {
  return (
    <div className={clsx('relative flex h-9 flex-1 items-center', className)}>
      <Search size={14} className="absolute left-3 text-slate-400" />
      <input
        type="text"
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-9 w-full rounded-lg border-0 bg-transparent pl-9 pr-3 text-sm text-slate-700 outline-none placeholder:text-slate-400 dark:text-slate-200"
      />
      {value && (
        <button
          onClick={() => onChange('')}
          className="absolute right-2 rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 dark:hover:bg-slate-800"
        >
          <X size={12} />
        </button>
      )}
    </div>
  )
}

/* ---------- SELECT ---------- */
interface SelectProps {
  value: string
  onChange: (value: string) => void
  children: ReactNode
  className?: string
  size?: 'sm' | 'md'
  disabled?: boolean
}

export function Select({ value, onChange, children, className = '', size = 'md', disabled }: SelectProps) {
  const h = size === 'sm' ? 'h-8 text-xs px-2.5 pr-7' : 'h-9 text-sm px-3 pr-8'
  return (
    <div className={clsx('relative', className, disabled && 'opacity-60 pointer-events-none')}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className={clsx(
          'appearance-none rounded-lg border border-slate-200 bg-white font-medium text-slate-700 outline-none transition-colors hover:border-slate-300 focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200',
          h,
        )}
      >
        {children}
      </select>
      <ChevronDown size={12} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-slate-400" />
    </div>
  )
}

import type { LucideProps } from 'lucide-react'
import type { ForwardRefExoticComponent, RefAttributes } from 'react'

type LucideIcon = ForwardRefExoticComponent<Omit<LucideProps, 'ref'> & RefAttributes<SVGSVGElement>>

/* ---------- TOGGLE ---------- */
interface ToggleItem {
  value: string
  label: string
  icon?: LucideIcon | React.ComponentType<{ size?: number }>
}

interface ToggleProps {
  items: ToggleItem[]
  value: string
  onChange: (value: string) => void
  className?: string
}

export function Toggle({ items, value, onChange, className = '' }: ToggleProps) {
  return (
    <div
      className={clsx(
        'inline-flex h-9 items-center gap-0.5 rounded-lg border border-slate-200 bg-slate-50 p-0.5 dark:border-slate-700 dark:bg-slate-800',
        className,
      )}
    >
      {items.map((it) => (
        <button
          key={it.value}
          onClick={() => onChange(it.value)}
          className={clsx(
            'inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs font-semibold transition-all',
            value === it.value
              ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-900 dark:text-white'
              : 'text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200',
          )}
        >
          {it.icon && <it.icon size={12} />}
          {it.label}
        </button>
      ))}
    </div>
  )
}
