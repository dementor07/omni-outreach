import { useMemo, useState } from 'react'
import { Search, UserRound, X } from 'lucide-react'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import { useListCampaigns } from '../hooks/useCampaigns'
import { Lead, useGetLead, useListLeads, useStopLead } from '../hooks/useLeads'

function formatDate(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

export default function Leads() {
  const campaignsQuery = useListCampaigns()
  const [campaignId, setCampaignId] = useState('')
  const [page, setPage] = useState(1)
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null)

  const leadsQuery = useListLeads(campaignId || undefined, page, 25)
  const stopLead = useStopLead()
  const selectedLead = useGetLead(selectedLeadId || undefined)

  const rows = leadsQuery.data?.leads || []
  const total = leadsQuery.data?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / 25))

  const columns = useMemo(
    () => [
      {
        key: 'name',
        header: 'Lead',
        render: (row: Lead) => (
          <div>
            <p className="font-medium text-slate-900">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || 'Unknown'}</p>
            <p className="text-xs text-slate-400">{row.company || '—'}</p>
          </div>
        ),
      },
      {
        key: 'headline',
        header: 'Headline',
        render: (row: Lead) => <span className="line-clamp-2">{row.headline || '—'}</span>,
      },
      {
        key: 'status',
        header: 'Status',
        render: (row: Lead) => <Badge label={row.status || 'active'} asStatus />,
      },
      { key: 'invited_at', header: 'Invited', render: (row: Lead) => formatDate(row.invited_at) },
      { key: 'accepted_at', header: 'Accepted', render: (row: Lead) => formatDate(row.accepted_at) },
      {
        key: 'stop',
        header: '',
        className: 'text-right',
        render: (row: Lead) => (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              void stopLead.mutateAsync({ leadId: row.id, campaignId: row.campaign_id })
            }}
            className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600 transition hover:bg-rose-50"
          >
            Stop
          </button>
        ),
      },
    ],
    [stopLead],
  )

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Leads</p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Inspect campaign leads without leaving the operator workflow</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
              Filter by campaign, inspect timelines, and stop problematic leads directly from the list.
            </p>
          </div>
          <div className="flex min-w-[320px] items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
            <Search size={16} className="text-slate-400" />
            <select
              value={campaignId}
              onChange={(event) => {
                setCampaignId(event.target.value)
                setPage(1)
              }}
              className="w-full bg-transparent text-sm text-slate-700 outline-none"
            >
              <option value="">Select a campaign</option>
              {(campaignsQuery.data || []).map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        {!campaignId ? (
          <EmptyState icon={UserRound} title="Choose a campaign first" description="The leads view is scoped by campaign so the table stays operationally useful." />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={rows}
              loading={leadsQuery.isLoading}
              onRowClick={(row) => setSelectedLeadId(row.id)}
              emptyMessage="No leads found for this campaign."
            />
            <div className="mt-4 flex items-center justify-between text-sm text-slate-500">
              <span>
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => setPage((current) => Math.max(1, current - 1))}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={page >= totalPages}
                  onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  className="rounded-lg border border-slate-200 px-3 py-1.5 disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </section>

      <LeadDrawer leadId={selectedLeadId} onClose={() => setSelectedLeadId(null)} query={selectedLead} />
    </div>
  )
}

function LeadDrawer({
  leadId,
  onClose,
  query,
}: {
  leadId: string | null
  onClose: () => void
  query: ReturnType<typeof useGetLead>
}) {
  const open = !!leadId
  const lead = query.data

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-900/30 backdrop-blur-sm">
      <button type="button" onClick={onClose} className="flex-1" aria-label="Close lead drawer" />
      <div className="h-full w-full max-w-xl overflow-y-auto border-l border-slate-200 bg-white shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-200 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-500">Lead Profile</p>
            <h2 className="mt-2 text-xl font-semibold text-slate-900">
              {lead ? `${lead.first_name || ''} ${lead.last_name || ''}`.trim() || 'Unknown lead' : 'Loading...'}
            </h2>
            {lead?.linkedin_url && (
              <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-sm text-sky-600 hover:text-sky-700">
                Open LinkedIn profile
              </a>
            )}
          </div>
          <button type="button" onClick={onClose} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-6 px-6 py-6">
          {query.isLoading ? (
            <div className="space-y-4">
              <div className="skeleton h-20 w-full" />
              <div className="skeleton h-40 w-full" />
            </div>
          ) : lead ? (
            <>
              <section className="grid gap-4 sm:grid-cols-2">
                <Detail label="Company" value={lead.company || '—'} />
                <Detail label="Status" value={<Badge label={lead.status || 'active'} asStatus />} />
                <Detail label="Headline" value={lead.headline || '—'} />
                <Detail label="Source" value={lead.source || '—'} />
                <Detail label="Invited" value={formatDate(lead.invited_at)} />
                <Detail label="Accepted" value={formatDate(lead.accepted_at)} />
              </section>

              <section>
                <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">Timeline</h3>
                <div className="mt-4 space-y-3">
                  {lead.timeline.length === 0 ? (
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-5 text-sm text-slate-500">
                      No events yet for this lead.
                    </div>
                  ) : (
                    lead.timeline.map((event, index) => (
                      <div key={`${event.event_type}-${index}`} className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <Badge label={event.event_type} variant="info" />
                            {event.channel && <Badge label={event.channel} asChannel />}
                          </div>
                          <span className="text-xs text-slate-400">{formatDate(event.occurred_at)}</span>
                        </div>
                        {event.meta && (
                          <pre className="mt-3 overflow-auto rounded-xl bg-white p-3 text-xs text-slate-600">
                            {JSON.stringify(event.meta, null, 2)}
                          </pre>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </section>
            </>
          ) : (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-5 text-sm text-rose-700">
              Failed to load lead details.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
      <div className="text-xs uppercase tracking-[0.14em] text-slate-400">{label}</div>
      <div className="mt-2 text-sm text-slate-800">{value}</div>
    </div>
  )
}
