import { clsx } from 'clsx'

import type { LucideProps } from 'lucide-react'
import type { ForwardRefExoticComponent, RefAttributes } from 'react'

type LucideIcon = ForwardRefExoticComponent<Omit<LucideProps, 'ref'> & RefAttributes<SVGSVGElement>>

interface TabItem {
  /** Canonical identifier. Either `value` (new) or `id` (legacy/design-tool) is accepted. */
  value?: string
  id?: string
  label: string
  icon?: LucideIcon | React.ComponentType<{ size?: number }>
  count?: number
}

interface TabsProps {
  /** Canonical: `items`. Aliased: `tabs` for design-tool migration. */
  items?: TabItem[]
  tabs?: TabItem[]
  /** Canonical: `value`. Aliased: `activeTab`. */
  value?: string
  activeTab?: string
  onChange: (value: string) => void
}

export default function Tabs({ items, tabs, value, activeTab, onChange }: TabsProps) {
  const resolvedItems = items ?? tabs ?? []
  const resolvedValue = value ?? activeTab ?? ''
  return (
    <div className="scrollbar-none flex min-w-0 items-center gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-800">
      {resolvedItems.map((it) => {
        const key = it.value ?? it.id ?? it.label
        const isActive = resolvedValue === key
        return (
          <button
            key={key}
            type="button"
            onClick={() => onChange(key)}
            className={clsx(
              'relative -mb-px inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-t-lg border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
              isActive
                ? 'border-brand-500 bg-brand-50/55 text-slate-950 dark:bg-brand-950/25 dark:text-white'
                : 'border-transparent text-slate-500 hover:bg-slate-100/70 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800/50 dark:hover:text-slate-200',
            )}
          >
            {it.icon && <it.icon size={14} />}
            {it.label}
            {it.count != null && (
              <span
                className={clsx(
                  'rounded px-1.5 py-0.5 text-[10px] font-semibold',
                  isActive ? 'bg-brand-50 text-brand-700' : 'bg-slate-100 text-slate-500',
                )}
              >
                {it.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
