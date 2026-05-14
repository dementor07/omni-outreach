import { clsx } from 'clsx'
import type { ReactNode } from 'react'

interface Column<T> {
  key: string
  header: string
  align?: 'left' | 'right'
  className?: string
  cellClassName?: string
  render?: (row: T) => ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  onRowClick?: (row: T) => void
  empty?: ReactNode
  emptyMessage?: ReactNode
  loading?: boolean
}

export default function DataTable<T extends { id?: string }>({ columns, rows, onRowClick, empty, emptyMessage, loading }: DataTableProps<T>) {
  if (loading) return <div className="p-4 space-y-2">{[0,1,2].map(i => <div key={i} className="h-10 skeleton" />)}</div>
  if (!rows.length && (empty || emptyMessage)) return <>{empty || <div className="p-6 text-center text-sm text-slate-500">{emptyMessage}</div>}</>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 dark:border-slate-800">
            {columns.map((c) => (
              <th
                key={c.key}
                className={clsx(
                  'whitespace-nowrap px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500 dark:text-slate-400',
                  c.align === 'right' && 'text-right',
                  c.className,
                )}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.id || i}
              className={clsx(
                'border-b border-slate-100 transition-colors last:border-b-0 dark:border-slate-800/60',
                onRowClick && 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50',
              )}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(
                    'px-3 py-3 align-middle text-slate-700 dark:text-slate-300',
                    c.align === 'right' && 'text-right tabular-nums',
                    c.cellClassName,
                  )}
                >
                  {c.render ? c.render(row) : (row as Record<string, unknown>)[c.key] as ReactNode}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
