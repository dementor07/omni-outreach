/**
 * DYNAMIC-001 — the generic renderer: one page that draws ANY stored view.
 *
 * Reads the omni_views row and renders its widget layout through ViewGrid.
 * After this page exists, new "screens" never require a frontend deploy —
 * they're rows the view architect (or the user, or an external agent) writes.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, RefreshCw, Trash2 } from 'lucide-react'
import { views } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import { ViewGrid } from '../components/ViewWidgets'
import ViewPromptBar from '../components/ViewPromptBar'
import { useToast } from '../components/Toast'

export default function DynamicView() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()

  const viewQ = useQuery({
    queryKey: ['view', id],
    queryFn: () => views.get(id),
    enabled: Boolean(id),
  })

  const remove = useMutation({
    mutationFn: () => views.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['views'] })
      toast.success('View deleted')
      navigate('/views')
    },
  })

  if (viewQ.isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" />
        ))}
      </div>
    )
  }

  if (viewQ.isError || !viewQ.data) {
    return (
      <EmptyState
        title="View not found"
        description="It may have been deleted."
        action={<Button icon={ArrowLeft} onClick={() => navigate('/views')}>Back to My Views</Button>}
      />
    )
  }

  const view = viewQ.data

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="My Views"
        title={view.name}
        description={view.description || view.prompt || undefined}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              icon={RefreshCw}
              onClick={() => qc.invalidateQueries({ queryKey: ['view-widget'] })}
            >
              Refresh
            </Button>
            <Button
              variant="danger"
              icon={Trash2}
              isLoading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Delete
            </Button>
          </div>
        }
      />

      <ViewPromptBar
        viewId={id}
        placeholder="Reshape this view — e.g. 'add a sends-by-status bar chart' or 'make the trend weekly'"
        suggestions={['Add campaign status', 'Show recent errors', 'Make the trend weekly']}
      />

      <ViewGrid layout={view.layout} />
    </div>
  )
}
