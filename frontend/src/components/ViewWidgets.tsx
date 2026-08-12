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
import { BarChart3, Hash, LineChart, List, Table2 } from 'lucide-react'
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
  const Icon = {
    stat: Hash,
    table: Table2,
    bar_chart: BarChart3,
    line_chart: LineChart,
    list: List,
  }[widget.type] ?? Hash
  return (
    <Card
      padding="sm"
      className={clsx(
        'group relative flex h-full min-h-[140px] flex-col overflow-hidden border-slate-200/80 bg-gradient-to-br from-white to-slate-50/50 transition duration-200 hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lg dark:border-slate-800 dark:from-slate-950 dark:to-slate-900/40 dark:hover:border-brand-900',
        WIDTH_CLASSES[widget.width ?? 2] ?? WIDTH_CLASSES[2],
        HEIGHT_CLASSES[widget.height ?? 1] ?? '',
      )}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <p className="flex min-w-0 items-center gap-2 truncate text-[11px] font-bold uppercase tracking-[0.11em] text-slate-500 dark:text-slate-400">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-600 transition group-hover:bg-brand-100 dark:bg-brand-950/50 dark:text-brand-300"><Icon size={13} /></span>
          <span className="truncate">{widget.title}</span>
        </p>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-slate-400 dark:bg-slate-800">Live</span>
      </div>
      <div className="min-h-0 flex-1">{children}</div>
    </Card>
  )
}

function LoadingState() {
  return <div className="h-full animate-pulse rounded-lg bg-slate-100 dark:bg-slate-800" />
}

function ErrorState({ message }: { message: string }) {
  return <div className="grid min-h-20 place-items-center rounded-xl border border-dashed border-rose-200 bg-rose-50/60 text-[12px] text-rose-600 dark:border-rose-900/50 dark:bg-rose-950/20">{message}</div>
}

function StatWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  const first = data?.rows[0]
  const col = data?.columns[0]
  const value = first && col ? first[col] : 0
  return (
    <p className="bg-gradient-to-r from-slate-950 to-brand-600 bg-clip-text text-4xl font-black tracking-tight text-transparent tabular-nums dark:from-white dark:to-brand-300">
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
        <thead className="sticky top-0 bg-white/95 backdrop-blur dark:bg-slate-950/95">
          <tr className="border-b border-slate-200 text-slate-500 dark:border-slate-700 dark:text-slate-400">
            {data.columns.map((c) => (
              <th key={c} className="whitespace-nowrap px-2 py-1.5 font-medium">{c.replace(/_/g, ' ')}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row, i) => (
            <tr key={i} className="border-b border-slate-100 transition hover:bg-brand-50/60 last:border-0 dark:border-slate-800 dark:hover:bg-brand-950/20">
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
            <div className="h-4 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
              <div
                className="h-full rounded-full bg-gradient-to-r from-brand-400 to-brand-600 shadow-[0_0_12px_rgba(20,184,166,.18)]"
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
        <li key={i} className="rounded-xl border border-transparent bg-slate-50 px-3 py-2 transition hover:border-brand-100 hover:bg-brand-50/60 dark:bg-slate-800/60 dark:hover:border-brand-900 dark:hover:bg-brand-950/20">
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
    <div className={clsx('grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4', className)}>
      {layout.map((widget) => (
        <WidgetRenderer key={widget.id} widget={widget} />
      ))}
    </div>
  )
}
