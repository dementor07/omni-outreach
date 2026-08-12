import { clsx } from 'clsx'
import { Search, X } from 'lucide-react'
import { Children, isValidElement, type ReactNode } from 'react'
import ThemedSelect, { type SelectOption } from './Select'

/* ---------- FILTER BAR ---------- */
interface FilterBarProps {
  children: ReactNode
  className?: string
}

export function FilterBar({ children, className = '' }: FilterBarProps) {
  return (
    <div
      className={clsx(
        'flex flex-wrap items-center gap-2 rounded-2xl border border-slate-200/80 bg-white/92 p-2.5 shadow-soft dark:border-slate-800 dark:bg-slate-900/90',
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

// Backwards-compatible wrapper around the themed listbox <Select>. Callers still
// pass <option> children; we flatten them into the options[] the themed control
// wants, so every existing FilterBar.Select gets the on-theme floating panel for
// free (the native <option> panel was the OS-owned eyesore).
export function Select({ value, onChange, children, className = '', size = 'md', disabled }: SelectProps) {
  const options: SelectOption[] = []
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return
    const props = child.props as { value?: string | number; children?: ReactNode }
    if (props.value === undefined) return
    options.push({ value: String(props.value), label: childText(props.children) })
  })
  return (
    <ThemedSelect
      value={value}
      onChange={onChange}
      options={options}
      size={size}
      disabled={disabled}
      className={className}
    />
  )
}

/** Best-effort text extraction from <option> children (string/number, or joined nodes). */
function childText(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(childText).join('')
  return ''
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
