import { FormEvent, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { Plus, Rocket, ChevronRight, Sparkles } from 'lucide-react'

// Layout & UI Components
import Badge from '../../components/Badge'
import Button from '../../components/Button'
import PageHeader from '../../components/PageHeader'
import Card from '../../components/Card'
import Modal from '../../components/Modal'
import { useToast } from '../../components/Toast'
import { canvas } from '../../api/v2'

// Hooks
import { useCreateCampaign, useListCampaigns } from '../../hooks/useCampaigns'

// Create-campaign form (the only piece of the old Campaigns/components subtree
// still in use — the rest was the dead in-page canvas, removed in the v2
// phase-out; the live canvas editor is CampaignEditor at /campaigns/:id).
import { CampaignPayload } from './types'
import { CampaignForm } from './components/Panels/CampaignForm'

const defaultCampaignForm: CampaignPayload = {
  name: '',
  daily_lead_cap: 50,
  invite_daily_cap: 20,
  simulation_mode: false,
  timezone: 'Asia/Kolkata',
  active_hours_start: 9,
  active_hours_end: 18,
  screening_prompt: '',
  sequence_mode: 'sequential',
}

/**
 * Campaigns LIST page (route `/campaigns`).
 *
 * Lists campaigns and offers "New Campaign"; clicking a card navigates to
 * `/campaigns/:id`, which is rendered by CampaignEditor (the real canvas).
 * This page never receives an :id, so it carries no canvas/graph state.
 */
export default function Campaigns() {
  const navigate = useNavigate()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()

  const campaignsQuery = useListCampaigns()
  const createCampaign = useCreateCampaign()

  const templatesQuery = useQuery({ queryKey: ['campaign-templates'], queryFn: canvas.templates })
  const fromTemplate = useMutation({
    mutationFn: (templateId: string) => canvas.createFromTemplate(templateId),
    onSuccess: (detail) => {
      setCreateOpen(false)
      navigate(`/campaigns/${detail.workflow.id}`)
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not create from template'),
  })

  const [createOpen, setCreateOpen] = useState(false)
  const [form, setForm] = useState<CampaignPayload>(defaultCampaignForm)

  // Auto-open the create modal when arriving with ?new=1 (e.g., from Dashboard).
  useEffect(() => {
    if (searchParams.get('new') === '1') {
      setForm(defaultCampaignForm)
      setCreateOpen(true)
      const next = new URLSearchParams(searchParams)
      next.delete('new')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams])

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Campaigns"
        eyebrow="Outreach"
        title="Campaigns"
        description="Manage your multi-channel outreach flows and lead pipelines."
        actions={
          <Button
            variant="primary"
            size="md"
            icon={Plus}
            onClick={() => { setForm(defaultCampaignForm); setCreateOpen(true) }}
          >
            New Campaign
          </Button>
        }
      />

      <section className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {campaignsQuery.data?.map((c) => (
          <Card
            key={c.id}
            padding="lg"
            className="group cursor-pointer transition-all hover:border-brand-200 hover:shadow-xl hover:shadow-brand-500/5 active:scale-[0.98]"
            onClick={() => navigate(`/campaigns/${c.id}`)}
          >
            <div className="flex items-start justify-between">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50 text-slate-400 transition-colors group-hover:bg-brand-50 group-hover:text-brand-500">
                <Rocket size={24} />
              </div>
              <Badge label={c.status || 'active'} asStatus />
            </div>
            <h3 className="mt-6 text-lg font-bold text-slate-900 dark:text-white">{c.name}</h3>
            <p className="mt-1 text-sm text-slate-500 line-clamp-1">{c.timezone} • {c.sequence_mode}</p>
            <div className="mt-8 flex items-center justify-between border-t border-slate-50 pt-4 text-xs font-bold uppercase tracking-widest text-slate-400 transition-colors group-hover:text-brand-600 dark:border-slate-800">
              View detail <ChevronRight size={14} />
            </div>
          </Card>
        ))}
      </section>

      <Modal title="Create Campaign" open={createOpen} onClose={() => setCreateOpen(false)}>
        {/* Cold-start fix: start from a ready-to-run template instead of a blank
            canvas. Picking one instantiates the graph and jumps to the editor. */}
        {(templatesQuery.data?.length ?? 0) > 0 && (
          <div className="mb-5">
            <p className="mb-2 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
              <Sparkles size={13} /> Start from a template
            </p>
            <div className="space-y-2">
              {templatesQuery.data!.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  disabled={fromTemplate.isPending}
                  onClick={() => fromTemplate.mutate(t.id)}
                  className="flex w-full items-start gap-3 rounded-xl border border-slate-200 p-3 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40 disabled:opacity-60 dark:border-slate-700 dark:hover:border-brand-700 dark:hover:bg-brand-900/10"
                >
                  <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/30 dark:text-brand-300">
                    <Rocket size={16} />
                  </span>
                  <span className="min-w-0">
                    <span className="block text-sm font-semibold text-slate-900 dark:text-white">{t.name}</span>
                    <span className="block text-xs text-slate-500">{t.summary}</span>
                  </span>
                </button>
              ))}
            </div>
            <div className="mt-4 flex items-center gap-3">
              <span className="h-px flex-1 bg-slate-100 dark:bg-slate-800" />
              <span className="text-[11px] font-medium uppercase tracking-wider text-slate-400">or start blank</span>
              <span className="h-px flex-1 bg-slate-100 dark:bg-slate-800" />
            </div>
          </div>
        )}
        <CampaignForm
          form={form}
          onChange={setForm}
          busy={createCampaign.isPending}
          submitLabel="Create Campaign"
          onSubmit={async (e: FormEvent) => {
            e.preventDefault()
            const c = await createCampaign.mutateAsync(form)
            setCreateOpen(false)
            navigate(`/campaigns/${c.id}`)
          }}
        />
      </Modal>
    </div>
  )
}
