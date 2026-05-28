import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KanbanSquare, DollarSign, Trophy, Plus } from 'lucide-react'
import { clsx } from 'clsx'
import { projections, events, type Deal } from '../api/v2'
import PageHeader from '../components/PageHeader'
import StatCard from '../components/StatCard'
import Card from '../components/Card'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import Modal from '../components/Modal'

// Pipeline stages (HubSpot-style). closed_won/closed_lost are terminal.
const STAGES: { key: string; label: string }[] = [
  { key: 'lead', label: 'Lead' },
  { key: 'qualified', label: 'Qualified' },
  { key: 'meeting', label: 'Meeting' },
  { key: 'proposal', label: 'Proposal' },
  { key: 'closed_won', label: 'Closed won' },
  { key: 'closed_lost', label: 'Closed lost' },
]

export default function Deals() {
  const qc = useQueryClient()
  const { data: deals = [], isLoading } = useQuery({
    queryKey: ['deals'],
    queryFn: () => projections.deals({ limit: 1000 }),
  })

  const moveMut = useMutation({
    mutationFn: ({ deal, stage }: { deal: Deal; stage: string }) =>
      events.publish({
        event_type: 'deal.stage_changed',
        entity_type: 'deal',
        entity_id: deal.id,
        payload: { stage },
      }),
    onMutate: async ({ deal, stage }) => {
      await qc.cancelQueries({ queryKey: ['deals'] })
      const previousDeals = qc.getQueryData<Deal[]>(['deals'])
      qc.setQueryData<Deal[]>(['deals'], (old = []) =>
        old.map((d) => (d.id === deal.id ? { ...d, stage } : d))
      )
      return { previousDeals }
    },
    onError: (err, newTodo, context) => {
      if (context?.previousDeals) {
        qc.setQueryData(['deals'], context.previousDeals)
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })

  const updateMut = useMutation({
    mutationFn: (updates: Partial<Deal> & { id: string }) =>
      events.publish({
        event_type: 'deal.updated',
        entity_type: 'deal',
        entity_id: updates.id,
        payload: { ...updates, id: undefined },
      }),
    onMutate: async (updates) => {
      await qc.cancelQueries({ queryKey: ['deals'] })
      const previousDeals = qc.getQueryData<Deal[]>(['deals'])
      qc.setQueryData<Deal[]>(['deals'], (old = []) =>
        old.map((d) => (d.id === updates.id ? { ...d, ...updates } : d))
      )
      return { previousDeals }
    },
    onError: (err, newTodo, context) => {
      if (context?.previousDeals) {
        qc.setQueryData(['deals'], context.previousDeals)
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: string) =>
      events.publish({
        event_type: 'deal.deleted',
        entity_type: 'deal',
        entity_id: id,
      }),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ['deals'] })
      const previousDeals = qc.getQueryData<Deal[]>(['deals'])
      qc.setQueryData<Deal[]>(['deals'], (old = []) => old.filter((d) => d.id !== id))
      return { previousDeals }
    },
    onError: (err, newTodo, context) => {
      if (context?.previousDeals) {
        qc.setQueryData(['deals'], context.previousDeals)
      }
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['deals'] })
    },
  })

  const [dragId, setDragId] = useState<string | null>(null)
  const [selectedDeal, setSelectedDeal] = useState<Deal | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [newDeal, setNewDeal] = useState({ name: '', value: '', currency: 'USD', stage: 'lead' })

  const createDealMut = useMutation({
    mutationFn: () =>
      events.publish({
        event_type: 'deal.created',
        entity_type: 'deal',
        payload: { name: newDeal.name, value: newDeal.value || null, currency: newDeal.currency, stage: newDeal.stage },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['deals'] })
      setShowCreate(false)
      setNewDeal({ name: '', value: '', currency: 'USD', stage: 'lead' })
    },
  })

  const byStage = useMemo(() => {
    const map = new Map<string, Deal[]>()
    for (const d of deals) {
      const arr = map.get(d.stage) ?? []
      arr.push(d)
      map.set(d.stage, arr)
    }
    return map
  }, [deals])

  const openValue = deals.filter((d) => !d.stage.startsWith('closed')).reduce((s, d) => s + Number(d.value ?? 0), 0)
  const wonValue = deals.filter((d) => d.stage === 'closed_won').reduce((s, d) => s + Number(d.value ?? 0), 0)
  const openCount = deals.filter((d) => !d.stage.startsWith('closed')).length

  function onDrop(stage: string) {
    if (!dragId) return
    const deal = deals.find((d) => d.id === dragId)
    if (deal && deal.stage !== stage) moveMut.mutate({ deal, stage })
    setDragId(null)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Deals"
        eyebrow="CRM"
        title="Deals"
        description="Your revenue pipeline. Drag a deal between stages to move it."
        actions={<Button variant="primary" size="md" icon={Plus} onClick={() => setShowCreate(true)}>New deal</Button>}
      />

      <section className="grid gap-3 sm:grid-cols-3">
        <StatCard label="Open pipeline" value={isLoading ? '—' : `$${openValue.toLocaleString()}`} icon={DollarSign} accent="brand" hint={`${openCount} open deals`} />
        <StatCard label="Closed won" value={isLoading ? '—' : `$${wonValue.toLocaleString()}`} icon={Trophy} accent="emerald" />
        <StatCard label="Total deals" value={isLoading ? '—' : deals.length} icon={KanbanSquare} accent="violet" />
      </section>

      {isLoading ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          {STAGES.map((s) => (
            <div key={s.key} className="flex flex-col rounded-xl">
              <div className="mb-2 flex items-center justify-between px-1">
                <div className="h-3 w-16 skeleton rounded" />
                <div className="h-4 w-6 skeleton rounded-md" />
              </div>
              <div className="mb-2 h-2 w-12 skeleton rounded px-1" />
              <div className="flex-1 space-y-2 rounded-xl bg-slate-50/60 p-2 dark:bg-slate-900/40">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-16 w-full skeleton rounded-lg" />
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : deals.length === 0 ? (
        <Card><EmptyState icon={KanbanSquare} title="No deals yet" description="Deals appear here when a workflow publishes a deal.created event." /></Card>
      ) : (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
          {STAGES.map((stage) => {
            const stageDeals = byStage.get(stage.key) ?? []
            const total = stageDeals.reduce((s, d) => s + Number(d.value ?? 0), 0)
            return (
              <div
                key={stage.key}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => onDrop(stage.key)}
                className="flex flex-col"
              >
                <div className="mb-2 flex items-center justify-between px-1">
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{stage.label}</p>
                  <span className="rounded-md bg-slate-100 px-1.5 text-[10px] font-bold tabular-nums text-slate-500 dark:bg-slate-800">{stageDeals.length}</span>
                </div>
                <p className="mb-2 px-1 text-[11px] tabular-nums text-slate-400">${total.toLocaleString()}</p>
                <div className="flex-1 space-y-2 rounded-xl bg-slate-50/60 p-2 dark:bg-slate-900/40">
                  {stageDeals.map((d) => (
                    <div
                      key={d.id}
                      draggable
                      onDragStart={() => setDragId(d.id)}
                      onDragEnd={() => setDragId(null)}
                      onClick={() => setSelectedDeal(d)}
                      className={clsx(
                        'cursor-grab rounded-lg border border-slate-200 bg-white p-2.5 shadow-sm transition-shadow hover:shadow-md hover:border-brand-300 active:cursor-grabbing dark:border-slate-700 dark:bg-slate-900 dark:hover:border-brand-500',
                        dragId === d.id && 'opacity-50',
                      )}
                    >
                      <p className="truncate text-[13px] font-medium text-slate-900 dark:text-white">{d.name}</p>
                      {d.value && (
                        <p className="mt-1 text-xs font-semibold tabular-nums text-slate-600 dark:text-slate-300">
                          {d.currency} {Number(d.value).toLocaleString()}
                        </p>
                      )}
                    </div>
                  ))}
                  {stageDeals.length === 0 && <p className="py-6 text-center text-[11px] text-slate-300">Drop here</p>}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {selectedDeal && (
        <Modal
          open={!!selectedDeal}
          onClose={() => setSelectedDeal(null)}
          title="Deal Details"
        >
          <div className="space-y-4 pt-4">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-500">Deal Name</label>
              <input
                type="text"
                value={selectedDeal.name}
                onChange={(e) => setSelectedDeal({ ...selectedDeal, name: e.target.value })}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500">Value</label>
                <div className="relative">
                  <span className="absolute left-3 top-2 text-sm text-slate-400">{selectedDeal.currency}</span>
                  <input
                    type="number"
                    value={selectedDeal.value ?? ''}
                    onChange={(e) => setSelectedDeal({ ...selectedDeal, value: e.target.value })}
                    className="w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-3 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                  />
                </div>
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500">Stage</label>
                <select
                  value={selectedDeal.stage}
                  onChange={(e) => setSelectedDeal({ ...selectedDeal, stage: e.target.value })}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                >
                  {STAGES.map((s) => (
                    <option key={s.key} value={s.key}>{s.label}</option>
                  ))}
                </select>
              </div>
            </div>
            
            <div className="flex items-center justify-between pt-6 border-t border-slate-100 dark:border-slate-800">
              <button
                onClick={() => {
                  deleteMut.mutate(selectedDeal.id)
                  setSelectedDeal(null)
                }}
                className="flex items-center gap-2 text-sm font-semibold text-rose-500 hover:text-rose-600 transition-colors"
              >
                Delete Deal
              </button>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={() => setSelectedDeal(null)}>Cancel</Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    updateMut.mutate({
                      id: selectedDeal.id,
                      name: selectedDeal.name,
                      value: selectedDeal.value,
                      stage: selectedDeal.stage,
                    })
                    setSelectedDeal(null)
                  }}
                >
                  Save Changes
                </Button>
              </div>
            </div>
          </div>
        </Modal>
      )}
      {showCreate && (
        <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Deal">
          <div className="space-y-4 pt-4">
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-500">Deal Name</label>
              <input
                type="text"
                autoFocus
                value={newDeal.name}
                onChange={(e) => setNewDeal({ ...newDeal, name: e.target.value })}
                placeholder="e.g. Acme Corp Enterprise License"
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500">Value</label>
                <input
                  type="number"
                  value={newDeal.value}
                  onChange={(e) => setNewDeal({ ...newDeal, value: e.target.value })}
                  placeholder="10000"
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-semibold text-slate-500">Currency</label>
                <select
                  value={newDeal.currency}
                  onChange={(e) => setNewDeal({ ...newDeal, currency: e.target.value })}
                  className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
                >
                  <option value="USD">USD</option>
                  <option value="EUR">EUR</option>
                  <option value="GBP">GBP</option>
                  <option value="INR">INR</option>
                </select>
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-semibold text-slate-500">Stage</label>
              <select
                value={newDeal.stage}
                onChange={(e) => setNewDeal({ ...newDeal, stage: e.target.value })}
                className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              >
                {STAGES.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
            </div>
            <div className="flex justify-end gap-2 pt-4 border-t border-slate-100 dark:border-slate-800">
              <Button variant="secondary" onClick={() => setShowCreate(false)}>Cancel</Button>
              <Button
                variant="primary"
                disabled={!newDeal.name.trim()}
                isLoading={createDealMut.isPending}
                onClick={() => createDealMut.mutate()}
              >
                Create Deal
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}
