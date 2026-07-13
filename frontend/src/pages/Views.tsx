/**
 * DYNAMIC-001 — My Views: the dynamic-interface home.
 *
 * Lists this workspace's stored views and hosts the view architect: describe
 * the screen you want in plain language and the AI composes it from the widget
 * vocabulary, saves it, and opens it. Views are data (omni_views), so nothing
 * here ever needs a frontend deploy.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { LayoutTemplate, Sparkles, Trash2 } from 'lucide-react'
import { views, type ViewDef } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import { useToast } from '../components/Toast'

const EXAMPLE_PROMPTS = [
  'A reply-triage board: recent inbound messages, positive replies first, plus reply counts by channel',
  'A pipeline overview: total contacts, contacts added this week as a trend, deals by stage, open tasks',
  'A deliverability cockpit: sends by status, failures by provider, a feed of recent errors',
]

function ViewCard({ view, onDelete }: { view: ViewDef; onDelete: (id: string) => void }) {
  const navigate = useNavigate()
  return (
    <Card hover padding="md" onClick={() => navigate(`/views/${view.id}`)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-[15px] font-semibold text-slate-900 dark:text-white">{view.name}</p>
          <p className="mt-0.5 line-clamp-2 text-[13px] text-slate-500 dark:text-slate-400">
            {view.description || `${view.layout.length} widgets`}
          </p>
        </div>
        <button
          type="button"
          className="rounded-lg p-1.5 text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950"
          title="Delete view"
          onClick={(e) => {
            e.stopPropagation()
            onDelete(view.id)
          }}
        >
          <Trash2 size={15} />
        </button>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Badge
          label={view.created_by === 'ai' ? 'AI-designed' : view.created_by}
          variant={view.created_by === 'ai' ? 'brand' : 'neutral'}
          size="sm"
        />
        <span className="text-[11px] text-slate-400">{view.layout.length} widgets</span>
      </div>
    </Card>
  )
}

export default function Views() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const toast = useToast()
  const [prompt, setPrompt] = useState('')

  const listQ = useQuery({ queryKey: ['views'], queryFn: views.list })

  const generate = useMutation({
    mutationFn: (p: string) => views.generate(p),
    onSuccess: (view) => {
      qc.invalidateQueries({ queryKey: ['views'] })
      toast.success(`View "${view.name}" created`)
      navigate(`/views/${view.id}`)
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'view generation failed'
      toast.error(detail)
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => views.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['views'] }),
  })

  const list = listQ.data ?? []

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Intelligence"
        title="My Views"
        description="Your own screens over your own data. Describe the view you want and the AI assembles it from live widgets — every view stays editable and is yours alone."
      />

      {/* The view architect */}
      <Card padding="md" className="space-y-3">
        <div className="flex items-center gap-2">
          <Sparkles size={16} className="text-brand-500" />
          <p className="text-[14px] font-semibold text-slate-900 dark:text-white">Describe a view</p>
        </div>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={2}
          placeholder="e.g. A morning dashboard: new contacts this week, sends by channel, recent replies, my open tasks"
          className="w-full resize-none rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-brand-950"
        />
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1.5">
            {EXAMPLE_PROMPTS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPrompt(p)}
                className="max-w-[280px] truncate rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-600 dark:border-slate-700 dark:text-slate-400"
                title={p}
              >
                {p}
              </button>
            ))}
          </div>
          <Button
            icon={Sparkles}
            isLoading={generate.isPending}
            disabled={prompt.trim().length < 8 || generate.isPending}
            onClick={() => generate.mutate(prompt.trim())}
          >
            Generate view
          </Button>
        </div>
      </Card>

      {/* Stored views */}
      {listQ.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-32 animate-pulse rounded-2xl bg-slate-100 dark:bg-slate-800" />
          ))}
        </div>
      ) : list.length === 0 ? (
        <EmptyState
          icon={LayoutTemplate}
          title="No views yet"
          description="Describe the screen you want above — the AI turns it into a live dashboard you own."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {list.map((v) => (
            <ViewCard key={v.id} view={v} onDelete={(id) => remove.mutate(id)} />
          ))}
        </div>
      )}
    </div>
  )
}
