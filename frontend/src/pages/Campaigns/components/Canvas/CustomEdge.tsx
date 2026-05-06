import React from 'react'
import { EdgeProps, EdgeLabelRenderer, getBezierPath, useReactFlow, BaseEdge } from '@xyflow/react'

// ── Edge label positioning helper ─────────────────────────────────────────
export function EdgeLabelPos({ x, y, className, children }: { x: number; y: number; className?: string; children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null)
  React.useLayoutEffect(() => {
    if (ref.current) {
      ref.current.style.transform = `translate(-50%, -50%) translate(${x}px,${y}px)`
    }
  }, [x, y])
  return (
    <div ref={ref} className={`rflow-edge-label nodrag nopan${className ? ` ${className}` : ''}`}>
      {children}
    </div>
  )
}

export function CustomEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  selected,
}: EdgeProps) {
  const { setEdges } = useReactFlow()
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  })

  return (
    <>
      <BaseEdge path={edgePath} markerEnd={markerEnd} style={{ ...style, strokeWidth: selected ? 3 : 2, stroke: selected ? '#0ea5e9' : '#cbd5e1' }} />
      <EdgeLabelRenderer>
        <EdgeLabelPos x={labelX} y={labelY}>
          <button
            aria-label="Delete connection"
            onClick={(e) => { e.stopPropagation(); setEdges((es) => es.filter((e) => e.id !== id)) }}
            className={`h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-[11px] font-bold text-slate-400 shadow-sm transition hover:text-rose-500 ${selected ? 'flex' : 'hidden'}`}
          >
            ×
          </button>
        </EdgeLabelPos>
      </EdgeLabelRenderer>
    </>
  )
}

export function TelemetryEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected, data }: EdgeProps) {
  const { setEdges } = useReactFlow()
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition })

  const activity = (data?.activity as number) || 0
  const backpressure = (data?.backpressure as number) || 0

  const strokeColor = backpressure > 5
    ? '#f59e0b'
    : activity >= 10 ? '#10b981'
    : activity >= 4 ? '#38bdf8'
    : activity >= 1 ? '#7dd3fc'
    : selected ? '#0ea5e9'
    : '#e2e8f0'
  const strokeWidth = selected ? 3 : 2 + Math.min(activity * 0.4, 3)
  const strokeDasharray = backpressure > 5 ? '6 3' : undefined

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: strokeColor, strokeWidth, strokeDasharray, transition: 'stroke 0.8s, stroke-width 0.8s' }} />
      <EdgeLabelRenderer>
        <EdgeLabelPos x={labelX} y={labelY} className="flex items-center gap-1">
          {activity > 0 && (
            <span className="rounded-full bg-emerald-500 px-1.5 py-0.5 text-[9px] font-black text-white shadow-sm">
              {activity}
            </span>
          )}
          {backpressure > 5 && (
            <span className="rounded-full bg-amber-400 px-1.5 py-0.5 text-[9px] font-black text-white shadow-sm">
              ⏳{backpressure}
            </span>
          )}
          <button
            aria-label="Delete connection"
            onClick={(e) => { e.stopPropagation(); setEdges((es) => es.filter((e) => e.id !== id)) }}
            className={`h-5 w-5 items-center justify-center rounded-full border border-slate-200 bg-white text-[11px] font-bold text-slate-400 shadow-sm transition hover:text-rose-500 ${selected ? 'flex' : 'hidden'}`}
          >
            ×
          </button>
        </EdgeLabelPos>
      </EdgeLabelRenderer>
    </>
  )
}
