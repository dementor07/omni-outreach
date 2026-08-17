import { useState } from 'react'
import type { ViewDef } from '../api/v2'
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
    </>
  )
}
