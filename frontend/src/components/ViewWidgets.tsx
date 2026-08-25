/**
 * DYNAMIC-001 — the widget renderers dynamic views are drawn with.
 *
 * One generic <WidgetRenderer> switches on widget.type; each widget runs its
 * own bound QuerySpec through POST /views/query and renders the result. All
 * charts are dependency-free (CSS bars / inline SVG) so the dynamic layer adds
 * no bundle weight.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { BarChart3, Check, Hash, LineChart, List, MessageSquarePlus, Table2, Trash2 } from 'lucide-react'
import { views, type ViewQueryResult, type WidgetInstance } from '../api/v2'
import Card from './Card'

export interface WidgetAnnotation {
  id: string
  widget_id: string
  note: string
}

interface AnnotationControls {
  annotationMode?: boolean
  annotations?: WidgetAnnotation[]
  onAddAnnotation?: (widgetId: string, note: string) => void
  onRemoveAnnotation?: (annotationId: string) => void
}

/** What an absent cell renders as. Shared so callers can detect it again. */
const EMPTY_CELL = '—'

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return EMPTY_CELL
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

function WidgetShell({
  widget,
  children,
  annotationMode = false,
  annotations = [],
  onAddAnnotation,
  onRemoveAnnotation,
}: { widget: WidgetInstance; children: React.ReactNode } & AnnotationControls) {
  const [composerOpen, setComposerOpen] = useState(false)
  const [note, setNote] = useState('')
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
        // Flat surface, not a gradient. from-white → to-slate-50/50 spanned two
        // values a half-step apart, so it cost a paint to render something no
        // one could see — and every card carrying the same faint wash is the
        // texture that makes a grid read as generated.
        // max-h bounds the runaway. Rows in this grid are auto-sized, so the
        // tallest card in a band sets the height of everything beside it — and
        // the recent-contacts list renders up to 20 rows, which pushed its band
        // past 800px and dragged the eight-row campaigns table up with it. Both
        // cards then sat mostly empty. Capping the card lets the short widgets
        // stay short and sends the long ones to their own scrollbar.
        'group relative flex h-full min-h-[140px] max-h-[26rem] flex-col overflow-hidden border-slate-200/80 bg-white transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-card dark:border-slate-800 dark:bg-slate-950 dark:hover:border-slate-700',
        annotationMode && 'border-brand-300 ring-2 ring-brand-100 hover:-translate-y-0 hover:border-brand-400 dark:border-brand-800 dark:ring-brand-950/70',
        WIDTH_CLASSES[widget.width ?? 2] ?? WIDTH_CLASSES[2],
        HEIGHT_CLASSES[widget.height ?? 1] ?? '',
      )}
      data-widget-id={widget.id}
      data-annotation-target={annotationMode ? 'true' : undefined}
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        {/* Sentence case, and the icon is muted rather than sitting in a brand
            chip. The chip was rose-on-rose at 28px on every card — four of them
            in a row across the stat strip, each showing the same glyph, all
            competing with the figure underneath, which is the only thing on the
            card anyone came to read. */}
        <p className="flex min-w-0 items-center gap-2 truncate text-[12px] font-medium text-slate-500 dark:text-slate-400">
          <Icon size={13} aria-hidden="true" className="shrink-0 text-slate-400 dark:text-slate-500" />
          <span className="truncate">{widget.title}</span>
        </p>
        <div className="flex shrink-0 items-center gap-1.5">
          {annotations.length > 0 && (
            <span className="rounded-full bg-brand-100 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wide text-brand-700 dark:bg-brand-950/60 dark:text-brand-300">
              {annotations.length} note{annotations.length === 1 ? '' : 's'}
            </span>
          )}
          {/* The "Live" pill used to sit on every widget unconditionally. A
              label that is true of all items distinguishes none of them, so it
              was pure chrome; the freshness it claimed to convey is already in
              the data. Only the annotate affordance remains, and only in the
              mode where it does something. */}
          {annotationMode && (
            <button
              type="button"
              onClick={() => setComposerOpen((current) => !current)}
              className="inline-flex items-center gap-1 rounded-md border border-brand-200 bg-white px-2 py-1 text-[10px] font-semibold text-brand-700 transition-colors hover:border-brand-400 hover:bg-brand-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/50 dark:border-brand-800 dark:bg-slate-900 dark:text-brand-300"
              aria-expanded={composerOpen}
              aria-label={`Annotate ${widget.title}`}
            >
              <MessageSquarePlus size={11} aria-hidden="true" /> Annotate
            </button>
          )}
        </div>
      </div>
      <div className="min-h-0 flex-1">{children}</div>
      {annotationMode && composerOpen && (
        <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50/70 p-2.5 dark:border-brand-900 dark:bg-brand-950/25">
          <label className="text-[10px] font-bold uppercase tracking-[0.1em] text-brand-700 dark:text-brand-300">
            Note for #{widget.id}
            <textarea
              autoFocus
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              placeholder="Describe exactly what should change in this widget…"
              className="mt-1.5 w-full resize-y rounded-lg border border-brand-200 bg-white px-2.5 py-2 text-[12px] font-normal normal-case tracking-normal text-slate-800 outline-none focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-brand-900 dark:bg-slate-950 dark:text-slate-100"
            />
          </label>
          <div className="mt-2 flex items-center justify-end gap-2">
            <button type="button" onClick={() => { setComposerOpen(false); setNote('') }} className="px-2 py-1 text-[11px] font-semibold text-slate-500">Cancel</button>
            <button
              type="button"
              disabled={note.trim().length < 2}
              onClick={() => {
                const next = note.trim()
                if (!next) return
                onAddAnnotation?.(widget.id, next)
                setNote('')
                setComposerOpen(false)
              }}
              className="inline-flex items-center gap-1 rounded-lg bg-brand-600 px-2.5 py-1.5 text-[11px] font-bold text-white disabled:opacity-40"
            >
              <Check size={12} /> Queue note
            </button>
          </div>
        </div>
      )}
      {annotationMode && annotations.length > 0 && (
        <div className="mt-3 space-y-1.5 border-t border-brand-100 pt-2.5 dark:border-brand-950">
          {annotations.map((annotation) => (
            <div key={annotation.id} className="flex items-start gap-2 rounded-lg bg-brand-50/80 px-2.5 py-2 text-[11px] leading-relaxed text-brand-950 dark:bg-brand-950/35 dark:text-brand-100">
              <span className="min-w-0 flex-1">{annotation.note}</span>
              <button type="button" onClick={() => onRemoveAnnotation?.(annotation.id)} className="shrink-0 rounded p-1 text-brand-500 hover:bg-brand-100 hover:text-brand-800 dark:hover:bg-brand-900" aria-label="Remove annotation"><Trash2 size={12} /></button>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function LoadingState() {
  // `.skeleton` is the app's shimmer, and it already carries the
  // reduced-motion opt-out. The previous plain `animate-pulse` block did not.
  return <div className="skeleton h-full min-h-16 w-full" />
}

/**
 * The widget-scale empty state.
 *
 * "No data" used to render as a 12px grey line in the top-left of the card,
 * leaving the rest of a 300px panel blank — which reads as a component that
 * failed rather than a question that legitimately has no answer yet. Centring
 * it and naming the reason turns the same fact into a finished state.
 */
function EmptyState({ message = 'Nothing to show yet' }: { message?: string }) {
  return (
    <div className="grid h-full min-h-16 place-items-center px-3 py-6 text-center">
      <p className="text-[12px] text-slate-400 dark:text-slate-500">{message}</p>
    </div>
  )
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
  // Solid ink, not gradient-clipped text. The gradient ran slate-950 → brand-600,
  // so the right-hand digits of every figure were rendered in the mid-brand rose
  // — the lightest part of the ramp, on a white card. It cost contrast on the one
  // element the page exists to communicate, and gradient-filled numerals are the
  // single most recognisable "generated dashboard" tell.
  return (
    <p className="text-4xl font-bold tracking-tight text-slate-900 tabular-nums dark:text-white">
      {formatCell(value ?? 0)}
    </p>
  )
}

function TableWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length) return <EmptyState message="No rows match this query" />
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

/**
 * DYNAMIC-003 — chart anatomy.
 *
 * Series colours come from ONE validated categorical palette, assigned by slot
 * position (see --viz-series-* in index.css). Position is the accessibility
 * mechanism: the slot ORDER is what keeps adjacent series apart under
 * colour-vision deficiency, so nothing here lets a caller pick a hue.
 *
 * Identity is never colour-alone — two or more series always get a legend, and
 * marks carry direct value labels. Text always wears text tokens, never the
 * series colour (the light-mode aqua/yellow slots are illegible as text).
 */
const SERIES_SLOTS = 8

function seriesColor(index: number): string {
  return `var(--viz-series-${(index % SERIES_SLOTS) + 1})`
}

interface Series { key: string; label: string; color: string }

function buildSeries(columns: string[], widget: WidgetInstance): Series[] {
  // Column 0 is the category / time bucket; every other column is a measure.
  return columns.slice(1).map((key, i) => ({
    key,
    label: widget.options?.series_labels?.[key] ?? key.replace(/_/g, ' '),
    color: seriesColor(i),
  }))
}

/**
 * A clean axis: a rounded top AND round ticks between 0 and it.
 *
 * Rounding the top alone was not enough. The top was chosen first and then cut
 * into `count` equal pieces, so a perfectly good max of 2,000 split three ways
 * printed 667 / 1,333 / 2,000 down the side of the weekly-contacts chart. The
 * step has to be the rounded quantity — the top is then whatever multiple of
 * that step clears the data.
 */
function niceScale(peak: number, targetTicks = 4): { max: number; ticks: number[] } {
  if (!(peak > 0)) return { max: 1, ticks: [0, 1] }
  const rawStep = peak / targetTicks
  const magnitude = 10 ** Math.floor(Math.log10(rawStep))
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= rawStep) ?? 10 * magnitude
  const max = Math.ceil(peak / step) * step
  const ticks: number[] = []
  // Half a step of slack absorbs float drift so the top tick is never dropped.
  for (let v = 0; v <= max + step / 2; v += step) ticks.push(Number(v.toPrecision(12)))
  return { max, ticks }
}

function ChartLegend({ series }: { series: Series[] }) {
  if (series.length < 2) return null   // one series: the title already names it
  return (
    <ul className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5 text-[10px] font-medium text-slate-600 dark:text-slate-300">
          <span
            aria-hidden="true"
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: s.color }}
          />
          <span className="truncate">{s.label}</span>
        </li>
      ))}
    </ul>
  )
}

function AxisCaption({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-1 text-center text-[9px] font-medium uppercase tracking-[0.1em] text-slate-400 dark:text-slate-500">
      {children}
    </p>
  )
}

function BarChartWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length || data.columns.length < 2) return <EmptyState message="Not enough data to chart yet" />

  const labelCol = data.columns[0]
  const series = buildSeries(data.columns, widget)
  const rows = data.rows.slice(0, 10)
  const stacked = widget.options?.stacked ?? false
  const showValues = widget.options?.value_labels ?? true

  // Stacked compares row TOTALS; grouped compares individual values.
  const rowTotal = (row: Record<string, unknown>) =>
    series.reduce((sum, s) => sum + (Number(row[s.key]) || 0), 0)
  const peak = stacked
    ? Math.max(...rows.map(rowTotal), 1)
    : Math.max(...rows.flatMap((r) => series.map((s) => Number(r[s.key]) || 0)), 1)
  const { max, ticks } = niceScale(peak)

  return (
    <div className="flex h-full flex-col">
      <ChartLegend series={series} />
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="relative">
          {/* Recessive hairline gridlines, drawn behind the marks. */}
          <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-28 right-12">
            {ticks.map((t) => (
              <span
                key={t}
                className="absolute top-0 bottom-0 w-px"
                style={{ left: `${(t / max) * 100}%`, background: 'var(--viz-grid)' }}
              />
            ))}
          </div>
          <div className="relative space-y-2">
            {rows.map((row, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-28 shrink-0 truncate text-[11px] text-slate-600 dark:text-slate-300" title={String(row[labelCol] ?? '')}>
                  {formatCell(row[labelCol])}
                </span>
                <div className="flex-1">
                  {stacked ? (
                    // One track; 2px surface gaps separate touching segments.
                    <div className="flex h-4 w-full items-stretch">
                      {series.map((s, si) => {
                        const value = Number(row[s.key]) || 0
                        if (value <= 0) return null
                        return (
                          <span
                            key={s.key}
                            title={`${s.label}: ${formatCell(value)}`}
                            className={clsx(
                              'h-full',
                              si === 0 && 'rounded-l-sm',
                              si === series.length - 1 && 'rounded-r',
                            )}
                            style={{
                              width: `${(value / max) * 100}%`,
                              background: s.color,
                              marginRight: si < series.length - 1 ? 2 : undefined,
                            }}
                          />
                        )
                      })}
                    </div>
                  ) : (
                    <div className="space-y-1">
                      {series.map((s) => {
                        const value = Number(row[s.key]) || 0
                        return (
                          <div key={s.key} className="flex items-center gap-1.5">
                            <div className="h-2.5 flex-1 rounded-sm" style={{ background: 'var(--viz-grid)' }}>
                              <div
                                className="h-full rounded-r-sm"
                                title={`${s.label}: ${formatCell(value)}`}
                                style={{ width: `${Math.max((value / max) * 100, value > 0 ? 1.5 : 0)}%`, background: s.color }}
                              />
                            </div>
                            {showValues && (
                              <span className="w-10 shrink-0 text-right text-[10px] tabular-nums text-slate-500 dark:text-slate-400">
                                {formatCell(value)}
                              </span>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
                {stacked && showValues && (
                  <span className="w-12 shrink-0 text-right text-[11px] tabular-nums text-slate-600 dark:text-slate-300">
                    {formatCell(rowTotal(row))}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
        {/* Value axis: the ticks carry every number the marks didn't label. */}
        <div className="mt-1.5 flex pl-28 pr-12">
          <div className="relative h-4 flex-1 border-t" style={{ borderColor: 'var(--viz-axis)' }}>
            {ticks.map((t) => (
              <span
                key={t}
                className="absolute top-0.5 -translate-x-1/2 text-[9px] tabular-nums text-slate-400 dark:text-slate-500"
                style={{ left: `${(t / max) * 100}%` }}
              >
                {formatCell(Math.round(t))}
              </span>
            ))}
          </div>
        </div>
      </div>
      {widget.options?.x_label && <AxisCaption>{widget.options.x_label}</AxisCaption>}
    </div>
  )
}

function LineChartWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length || data.columns.length < 2) return <EmptyState message="Not enough data to chart yet" />

  const bucketCol = data.columns[0]
  const series = buildSeries(data.columns, widget)
  const rows = data.rows
  const showValues = widget.options?.value_labels ?? true

  // Uniform scaling (meet, not none) so end markers stay circular and stroke
  // weight is honest. Padding leaves room for tick text inside the viewBox.
  const W = 320
  const H = 132
  const PAD = { top: 8, right: 34, bottom: 20, left: 30 }
  const plotW = W - PAD.left - PAD.right
  const plotH = H - PAD.top - PAD.bottom

  const peak = Math.max(...rows.flatMap((r) => series.map((s) => Number(r[s.key]) || 0)), 1)
  const { max, ticks } = niceScale(peak, 3)
  const x = (i: number) => PAD.left + (rows.length > 1 ? (i / (rows.length - 1)) * plotW : plotW / 2)
  const y = (v: number) => PAD.top + plotH - (v / max) * plotH

  return (
    <div className="flex h-full flex-col">
      <ChartLegend series={series} />
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet" className="min-h-0 w-full flex-1" role="img">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--viz-grid)" strokeWidth="1" />
            <text x={PAD.left - 4} y={y(t) + 3} textAnchor="end" fontSize="8" fill="var(--viz-ink-muted)">
              {Math.round(t).toLocaleString()}
            </text>
          </g>
        ))}
        <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke="var(--viz-axis)" strokeWidth="1" />
        {series.map((s, si) => {
          const points = rows.map((r, i) => ({ x: x(i), y: y(Number(r[s.key]) || 0) }))
          const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
          const last = points[points.length - 1]
          const lastValue = Number(rows[rows.length - 1]?.[s.key]) || 0
          return (
            <g key={s.key}>
              {series.length === 1 && (
                <path d={`${path} L${last.x},${y(0)} L${points[0].x},${y(0)} Z`} fill={s.color} opacity={0.1} />
              )}
              <path d={path} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {/* End marker: 2px surface ring keeps it legible where lines cross. */}
              <circle cx={last.x} cy={last.y} r="4" fill={s.color} stroke="var(--viz-surface)" strokeWidth="2" />
              {showValues && (
                <text x={last.x + 7} y={last.y + 3} fontSize="9" fill="var(--viz-ink-muted)" fontWeight="600">
                  {lastValue.toLocaleString()}
                </text>
              )}
            </g>
          )
        })}
        {/* Time axis: first / middle / last only — enough to orient, no crowding. */}
        {[0, Math.floor((rows.length - 1) / 2), rows.length - 1]
          .filter((i, idx, arr) => i >= 0 && arr.indexOf(i) === idx)
          .map((i) => (
            <text
              key={i}
              x={x(i)}
              y={H - 6}
              textAnchor={i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle'}
              fontSize="8"
              fill="var(--viz-ink-muted)"
            >
              {formatCell(rows[i]?.[bucketCol])}
            </text>
          ))}
      </svg>
      {widget.options?.x_label && <AxisCaption>{widget.options.x_label}</AxisCaption>}
    </div>
  )
}

function ListWidget({ widget }: { widget: WidgetInstance }) {
  const { data, isLoading, error } = useWidgetData(widget)
  if (isLoading) return <LoadingState />
  if (error) return <ErrorState message="query failed" />
  if (!data?.rows.length) return <EmptyState message="No rows match this query" />
  const [titleCol, subtitleCol] = data.columns
  return (
    <ul className="space-y-1.5 overflow-auto">
      {data.rows.slice(0, 20).map((row, i) => {
        const title = formatCell(row[titleCol])
        const subtitle = subtitleCol ? formatCell(row[subtitleCol]) : ''
        // formatCell renders a null as an em dash, and most contacts carry no
        // name, so every row printed "—" above a second "—" — a stack of
        // identical placeholders that reads as a failed component rather than
        // as missing data. Say "Unnamed" once, and drop the subtitle line
        // entirely when it has nothing of its own to add.
        const hasTitle = title !== EMPTY_CELL
        const hasSubtitle = subtitle && subtitle !== EMPTY_CELL && subtitle !== title
        return (
          <li key={i} className="rounded-xl border border-transparent bg-slate-50 px-3 py-2 transition-colors hover:border-brand-100 hover:bg-brand-50/60 dark:bg-slate-800/60 dark:hover:border-brand-900 dark:hover:bg-brand-950/20">
            <p
              className={clsx(
                'truncate text-[12px]',
                hasTitle
                  ? 'font-medium text-slate-800 dark:text-slate-200'
                  : 'italic text-slate-400 dark:text-slate-500',
              )}
            >
              {hasTitle ? title : 'Unnamed'}
            </p>
            {hasSubtitle && (
              <p className="truncate text-[11px] text-slate-500 dark:text-slate-400">{subtitle}</p>
            )}
          </li>
        )
      })}
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

export function WidgetRenderer({ widget, ...annotationControls }: { widget: WidgetInstance } & AnnotationControls) {
  const Component = WIDGET_COMPONENTS[widget.type]
  return (
    <WidgetShell widget={widget} {...annotationControls}>
      {Component ? <Component widget={widget} /> : <ErrorState message={`unknown widget type ${widget.type}`} />}
    </WidgetShell>
  )
}

export function ViewGrid({
  layout,
  className,
  annotationMode = false,
  annotations = [],
  onAddAnnotation,
  onRemoveAnnotation,
}: { layout: WidgetInstance[]; className?: string } & AnnotationControls) {
  return (
    <div className={clsx('grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4', annotationMode && 'rounded-2xl bg-brand-50/45 p-3 ring-1 ring-brand-100 dark:bg-brand-950/10 dark:ring-brand-950', className)}>
      {layout.map((widget) => (
        <WidgetRenderer
          key={widget.id}
          widget={widget}
          annotationMode={annotationMode}
          annotations={annotations.filter((annotation) => annotation.widget_id === widget.id)}
          onAddAnnotation={onAddAnnotation}
          onRemoveAnnotation={onRemoveAnnotation}
        />
      ))}
    </div>
  )
}
