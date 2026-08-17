import { useMemo, useState } from 'react'
import { MessageSquare } from 'lucide-react'
import type { ThreadAnchor, ViewDef } from '../api/v2'
import AgentThreadPanel from './AgentThreadPanel'
import Button from './Button'
import ViewPromptBar from './ViewPromptBar'
import { ViewGrid, type WidgetAnnotation } from './ViewWidgets'

interface Props {
  view: ViewDef
  label?: string
  placeholder?: string
  suggestions?: string[]
  onUpdated?: (view: ViewDef) => void
}

function annotationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `annotation-${Date.now()}-${Math.random()}`
}

export default function ComposableView({ view, label, placeholder, suggestions, onUpdated }: Props) {
  const [annotationMode, setAnnotationMode] = useState(false)
  const [annotations, setAnnotations] = useState<WidgetAnnotation[]>([])
  const [composerOpen, setComposerOpen] = useState(false)
  const [threadOpen, setThreadOpen] = useState(false)

  const addAnnotation = (widgetId: string, note: string) => {
    setAnnotations((current) => [
      ...current,
      { id: annotationId(), widget_id: widgetId, note },
    ])
  }

  const removeAnnotation = (annotationIdToRemove: string) => {
    setAnnotations((current) => current.filter((annotation) => annotation.id !== annotationIdToRemove))
  }

  const clearAnnotations = () => setAnnotations([])

  // AGENT-THREAD-001: the widget notes staged in annotation mode are exactly
  // what a thread turn pins, so the two share one piece of state rather than
  // asking the operator to annotate twice.
  const pendingAnchors = useMemo<ThreadAnchor[]>(
    () => annotations.map((annotation) => ({ ref: annotation.widget_id, note: annotation.note })),
    [annotations],
  )
  const anchorLabels = useMemo(
    () =>
      Object.fromEntries(
        view.layout.map((widget) => [widget.id, widget.title || widget.type]),
      ),
    [view.layout],
  )

  return (
    <>
      <ViewPromptBar
        view={view}
        label={label}
        placeholder={placeholder}
        suggestions={suggestions}
        annotationMode={annotationMode}
        annotations={annotations}
        onToggleAnnotationMode={() => setAnnotationMode((current) => !current)}
        onClearAnnotations={clearAnnotations}
        onUpdated={onUpdated}
        expanded={composerOpen}
        onExpand={() => setComposerOpen(true)}
        onClose={() => {
          setComposerOpen(false)
          setAnnotationMode(false)
        }}
      />
      {annotationMode && (
        <div className="rounded-xl border border-brand-200 bg-brand-50/70 px-3 py-2 text-[11px] leading-relaxed text-brand-900 dark:border-brand-900 dark:bg-brand-950/25 dark:text-brand-100">
          <strong>Annotation mode is active.</strong> Each widget is now a visible target. Use its Annotate button to queue a scoped note; nothing changes until you apply through the selected connected API or review a validated harness result.
        </div>
      )}
      <ViewGrid
        layout={view.layout}
        annotationMode={annotationMode}
        annotations={annotations}
        onAddAnnotation={addAnnotation}
        onRemoveAnnotation={removeAnnotation}
      />

      {!threadOpen && (
        <div className="flex justify-end">
          <Button size="xs" variant="ghost" icon={MessageSquare} onClick={() => setThreadOpen(true)}>
            Ask about this view
            {pendingAnchors.length > 0 && ` (${pendingAnchors.length} pinned)`}
          </Button>
        </div>
      )}

      {threadOpen && (
        <div className="fixed inset-y-0 right-0 z-40 w-full max-w-[26rem] shadow-2xl">
          <AgentThreadPanel
            targetType="view"
            targetId={view.id}
            anchorLabels={anchorLabels}
            pendingAnchors={pendingAnchors}
            onStageAnchor={(anchor) => addAnnotation(anchor.ref, anchor.note)}
            onRemoveAnchor={(ref) =>
              setAnnotations((current) => current.filter((annotation) => annotation.widget_id !== ref))
            }
            onClearAnchors={clearAnnotations}
            onClose={() => setThreadOpen(false)}
          />
        </div>
      )}
    </>
  )
}
