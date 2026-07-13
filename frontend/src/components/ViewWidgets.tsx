/**
 * DYNAMIC-001 — the widget renderers dynamic views are drawn with.
 *
 * One generic <WidgetRenderer> switches on widget.type; each widget runs its
 * own bound QuerySpec through POST /views/query and renders the result. All
 * charts are dependency-free (CSS bars / inline SVG) so the dynamic layer adds
 * no bundle weight.
 */
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { views, type ViewQueryResult, type WidgetInstance } from '../api/v2'
import Card from './Card'

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2)
  }
  const str = String(value)
  // ISO timestamps → compact local date
  if (/^\d{4}-\d{2}-\d{2}T/.test(str)) {
    const d = new Date(str)
    if (!Number.isNaN(d.getTime())) {
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
    }
  }
  return str
}

function useWidgetData(widget: WidgetInstance) {
  return useQuery<ViewQueryResult>({
    queryKey: ['view-widget', widget.id, widget.query],
    queryFn: () => views.query(widget.query),
    staleTime: 30_000,
  })
}

// Static class maps (Tailwind can't see dynamic strings). Mobile collapses to
// one column; span classes only apply from sm/lg up.
const WIDTH_CLASSES: Record<number, string> = {
  1: 'sm:col-span-1',
  2: 'sm:col-span-2',
  3: 'sm:col-span-2 lg:col-span-3',
  4: 'sm:col-span-2 lg:col-span-4',
}
const HEIGHT_CLASSES: Record<number, string> = {
  1: '',
  2: 'sm:row-span-2',
  3: 'sm:row-span-3',
}

function WidgetShell({ widget, children }: { widget: WidgetInstance; children: React.ReactNode }) {
  return (
    <Card
      padding="sm"
      className={clsx(
        'flex h-full min-h-[120px] flex-col overflow-hidden',
        WIDTH_CLASSES[widget.width ?? 2] ?? WIDTH_CLASSES[2],
        HEIGHT_CLASSES[widget.height ?? 1] ?? '',
      )}
    >
      <p className="mb-2 truncate text-[12px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {widget.title}
      </p>
      <div className="min-h-0 flex-1">{children}</div>
    </Card>
  )
}

function LoadingState() {
  return <div className="h-full animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
}

function ErrorState({ message }: { message: string }) {
  return <p className="text-[12px] text-rose-500">{message}</p>
}

function StatWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  const first = data?.rows[0]
  const col = data?.columns[0]
  const value = first && col ? first[col] : 0
  return (
    <p className="text-3xl font-bold tabular-nums text-slate-900 dark:text-white">
      {formatCell(value ?? 0)}
    </p>
  )
}

function TableWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length) return <p className="text-[12px] text-slate-400">No data</p>
  return (
    <div className="h-full overflow-auto">
      <table className="w-full text-left text-[12px]">
        <thead>
          <tr className="border-b border-slate-200 text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {data.columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-2 py-1.5 font-medium">{c.replace(/_/g, ' ')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 last:border-0 dark:border-slate-800">
              {data.columns.map((c) => (
                <td key={c} className="max-w-[220px] truncate px-2 py-1.5 text-slate-700 dark:text-slate-300">
                  {formatCell(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BarChartWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length || data.columns.length < 2) return <p className="text-[12px] text-slate-400">No data</p>
  const [labelCol, valueCol] = data.columns
  const rows = data.rows.slice(0, 10)
  const max = Math.max(...rows.map((r) => Number(r[valueCol]) || 0), 1)
  return (
    <div className="space-y-1.5 overflow-auto">
      {rows.map((row, i) => {
        const value = Number(row[valueCol]) || 0
        return (
          <div key={i} className="flex items-center gap-2">
            <span className="w-28 shrink-0 truncate text-[11px] text-slate-500 dark:text-slate-400">
              {formatCell(row[labelCol])}
            </span>
            <div className="h-4 flex-1 overflow-hidden rounded bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded bg-brand-500/80"
                style={{ width: `${Math.max((value / max) * 100, 2)}%` }}
              />
            </div>
            <span className="w-12 shrink-0 text-right text-[11px] tabular-nums text-slate-600 dark:text-slate-300">
              {formatCell(value)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function LineChartWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length || data.columns.length < 2) return <p className="text-[12px] text-slate-400">No data</p>
  const valueCol = data.columns[1]
  const points = data.rows.map((r) => Number(r[valueCol]) || 0)
  const max = Math.max(...points, 1)
  const w = 100
  const h = 36
  const step = points.length > 1 ? w / (points.length - 1) : w
  const path = points
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(2)},${(h - (v / max) * (h - 4) - 2).toFixed(2)}`)
    .join(' ')
  const first = data.rows[0]?.[data.columns[0]]
  const last = data.rows[data.rows.length - 1]?.[data.columns[0]]
  return (
    <div className="flex h-full flex-col">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className="min-h-0 w-full flex-1">
        <path d={`${path} L${w},${h} L0,${h} Z`} className="fill-brand-500/10" stroke="none" />
        <path d={path} className="stroke-brand-500" strokeWidth="1.5" fill="none" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-1 flex justify-between text-[10px] text-slate-400">
        <span>{formatCell(first)}</span>
        <span>{formatCell(last)}</span>
      </div>
    </div>
  )
}

function ListWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length) return <p className="text-[12px] text-slate-400">No data</p>
  const [titleCol, subtitleCol] = data.columns
  return (
    <ul className="space-y-1.5 overflow-auto">
      {data.rows.slice(0, 20).map((row, i) => (
        <li key={i} className="rounded-lg bg-slate-50 px-2.5 py-1.5 dark:bg-slate-800/60">
          <p className="truncate text-[12px] font-medium text-slate-800 dark:text-slate-200">
            {formatCell(row[titleCol])}
          </p>
          {subtitleCol && (
            <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">
              {formatCell(row[subtitleCol])}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}

const WIDGET_COMPONENTS: Record<string, (props: { widget: WidgetInstance }) => JSX.Element> = {
  stat: StatWidget,
  table: TableWidget,
  bar_chart: BarChartWidget,
  line_chart: LineChartWidget,
  list: ListWidget,
}

export function WidgetRenderer({ widget }: { widget: WidgetInstance }) {
  const Component = WIDGET_COMPONENTS[widget.type]
  return (
    <WidgetShell widget={widget}>
      {Component ? <Component widget={widget} /> : <ErrorState message={`unknown widget type ${widget.type}`} />}
    </WidgetShell>
  )
}

export function ViewGrid({ layout, className }: { layout: WidgetInstance[]; className?: string }) {
  return (
    <div className={clsx('grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {layout.map((widget) => (
        <WidgetRenderer key={widget.id} widget={widget} />
      ))}
    </div>
  )
}
