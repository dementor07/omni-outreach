/**
 * DYNAMIC-001 — the generic renderer: one page that draws ANY stored view.
 *
 * Reads the omni_views row and renders its widget layout through ViewGrid.
 * After this page exists, new "screens" never require a frontend deploy —
 * they're rows the view architect (or the user, or an external agent) writes.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, RefreshCw, Sparkles, Trash2 } from 'lucide-react'
import { views } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import { ViewGrid } from '../components/ViewWidgets'
import { useToast } from '../components/Toast'

export default function DynamicView() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [instruction, setInstruction] = useState('')

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

  // DYNAMIC-002: reshape this view by describing the change.
  const edit = useMutation({
    mutationFn: (text: string) => views.edit(id, text),
    onSuccess: (updated) => {
      qc.setQueryData(['view', id], updated)
      qc.invalidateQueries({ queryKey: ['view-widget'] })
      qc.invalidateQueries({ queryKey: ['views'] })
      setInstruction('')
      toast.success('View updated')
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'could not apply the change'
      toast.error(detail)
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

      {/* DYNAMIC-002: reshape this view by describing the change. */}
      <Card padding="sm" className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Sparkles size={16} className="hidden shrink-0 text-brand-500 sm:block" />
        <input
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && instruction.trim().length >= 3 && !edit.isPending) {
              edit.mutate(instruction.trim())
            }
          }}
          placeholder="Reshape this view — e.g. 'add a sends-by-status bar chart', 'make the trend weekly', 'drop the tasks widget'"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-brand-950"
        />
        <Button
          icon={Sparkles}
          isLoading={edit.isPending}
          disabled={instruction.trim().length < 3 || edit.isPending}
          onClick={() => edit.mutate(instruction.trim())}
        >
          {edit.isPending ? 'Applying…' : 'Apply'}
        </Button>
      </Card>

      <ViewGrid layout={view.layout} />
    </div>
  )
}
