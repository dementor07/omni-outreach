import { useMemo, useRef, useState } from 'react'
import { Search, UserRound, UserPlus, X, CheckSquare, Square, StopCircle, RotateCcw, Trash2, Upload, ExternalLink, Download } from 'lucide-react'

import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import EmptyState from '../components/EmptyState'
import { useListCampaigns } from '../hooks/useCampaigns'
import { Lead, useGetLead, useListLeads, useStopLead, useBulkLeadAction, useCsvUpload, useCreateLead, CsvUploadResult, LeadImportPayload } from '../hooks/useLeads'

function formatDate(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

const SOURCE_COLORS: Record<string, string> = {
  apollo: 'bg-violet-100 text-violet-700',
  apify_jobs: 'bg-sky-100 text-sky-700',
  csv: 'bg-amber-100 text-amber-700',
  manual: 'bg-slate-100 text-slate-600',
  proxycurl: 'bg-emerald-100 text-emerald-700',
  github: 'bg-gray-100 text-gray-600',
  hunter: 'bg-orange-100 text-orange-700',
}

function SourceBadge({ source }: { source?: string | null }) {
  if (!source) return null
  const cls = SOURCE_COLORS[source] ?? 'bg-slate-100 text-slate-600'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}>
      {source}
    </span>
  )
}

export default function Leads() {
  const campaignsQuery = useListCampaigns()
  const [campaignId, setCampaignId] = useState('')
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [selectedLeadId, setSelectedLeadId] = useState<string | null>(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [bulkTarget, setBulkTarget] = useState('')
  const [csvResult, setCsvResult] = useState<CsvUploadResult | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const csvInputRef = useRef<HTMLInputElement>(null)

  const leadsQuery = useListLeads(campaignId || undefined, page, 25, search || undefined, statusFilter || undefined)
  const stopLead = useStopLead()
  const bulkAction = useBulkLeadAction()
  const csvUpload = useCsvUpload()
  const createLead = useCreateLead()
  const selectedLead = useGetLead(selectedLeadId || undefined)

  function handleCsvFile(file: File | undefined) {
    if (!file || !campaignId) return
    csvUpload.mutate(
      { campaignId, file },
      {
        onSuccess: (result) => setCsvResult(result),
        onError: () => setCsvResult(null),
      },
    )
  }

  const rows = leadsQuery.data?.leads || []
  const total = leadsQuery.data?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / 25))

  const columns = useMemo(
    () => [
      {
        key: 'select',
        header: (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              if (selectedIds.size === rows.length && rows.length > 0) {
                setSelectedIds(new Set())
              } else {
                setSelectedIds(new Set(rows.map((r) => r.id)))
              }
            }}
            className="text-slate-400 hover:text-sky-600"
          >
            {selectedIds.size === rows.length && rows.length > 0 ? <CheckSquare size={16} /> : <Square size={16} />}
          </button>
        ),
        className: 'w-10',
        render: (row: Lead) => (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setSelectedIds((prev) => {
                const next = new Set(prev)
                if (next.has(row.id)) next.delete(row.id)
                else next.add(row.id)
                return next
              })
            }}
            className="text-slate-400 hover:text-sky-600"
          >
            {selectedIds.has(row.id) ? <CheckSquare size={16} className="text-sky-600" /> : <Square size={16} />}
          </button>
        ),
      },
      {
        key: 'name',
        header: 'Lead',
        render: (row: Lead) => (
          <div>
            <p className="font-medium text-slate-900">{`${row.first_name || ''} ${row.last_name || ''}`.trim() || 'Unknown'}</p>
            <p className="text-xs text-slate-400">{row.company || '—'}</p>
            <SourceBadge source={row.source} />
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
    [stopLead, selectedIds, rows],
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
              aria-label="Select campaign"
              value={campaignId}
              onChange={(event) => {
                setCampaignId(event.target.value)
                setPage(1)
                setCsvResult(null)
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

          {/* CSV upload + Add Lead buttons — only active when a campaign is selected */}
          <div className="flex gap-2">
            <input
              ref={csvInputRef}
              type="file"
              accept=".csv"
              aria-label="Select CSV file to import leads"
              className="hidden"
              onChange={(e) => handleCsvFile(e.target.files?.[0])}
            />
            <button
              type="button"
              disabled={!campaignId || csvUpload.isPending}
              onClick={() => csvInputRef.current?.click()}
              aria-label="Upload CSV file of leads"
              className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm transition hover:border-sky-400 hover:text-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Upload size={15} />
              {csvUpload.isPending ? 'Uploading…' : 'Upload CSV'}
            </button>
            <button
              type="button"
              disabled={!campaignId}
              onClick={async () => {
                const { data } = await api.get(`/leads/export?campaign_id=${campaignId}`, { responseType: 'blob' })
                const url = window.URL.createObjectURL(new Blob([data]))
                const link = document.createElement('a')
                link.href = url
                link.setAttribute('download', `leads_${campaignId}.csv`)
                document.body.appendChild(link)
                link.click()
                link.remove()
              }}
              className="flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-medium text-slate-700 shadow-sm transition hover:border-sky-400 hover:text-sky-600 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Download size={15} />
              Export CSV
            </button>
            <button
              type="button"
              disabled={!campaignId}
              onClick={() => setShowAddModal(true)}
              aria-label="Add lead manually"
              className="flex items-center gap-2 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm font-medium text-sky-700 shadow-sm transition hover:bg-sky-100 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <UserPlus size={15} />
              Add Lead
            </button>
          </div>
        </div>

        {/* Search + Filter bar */}
        {campaignId && (
          <div className="mt-4 flex flex-wrap gap-3">
            <div className="flex flex-1 items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2">
              <Search size={14} className="text-slate-400" />
              <input
                type="text"
                placeholder="Search leads by name, company, email..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1) }}
                className="w-full text-sm text-slate-700 outline-none placeholder:text-slate-400"
              />
              {search && (
                <button aria-label="Clear search" onClick={() => setSearch('')} className="text-slate-400 hover:text-slate-600">
                  <X size={14} />
                </button>
              )}
            </div>
            <select
              aria-label="Filter by status"
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1) }}
              className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none"
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="stopped">Stopped</option>
              <option value="bounced">Bounced</option>
            </select>
          </div>
        )}
      </section>

      {/* CSV upload result banner */}
      {csvResult && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-5 py-4">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-semibold text-emerald-800">
                CSV import complete — {csvResult.imported} imported, {csvResult.skipped} skipped
                {csvResult.invalid > 0 && `, ${csvResult.invalid} invalid`}
              </p>
              {csvResult.errors.length > 0 && (
                <ul className="mt-2 space-y-0.5 text-xs text-rose-700">
                  {csvResult.errors.map((e, i) => <li key={i}>{e}</li>)}
                </ul>
              )}
            </div>
            <button
              type="button"
              aria-label="Dismiss import result"
              onClick={() => setCsvResult(null)}
              className="mt-0.5 shrink-0 text-slate-400 hover:text-slate-600"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        {!campaignId ? (
          <EmptyState icon={UserRound} title="Choose a campaign first" description="The leads view is scoped by campaign so the table stays operationally useful." />
        ) : (
          <>
            {/* Bulk action toolbar */}
            {selectedIds.size > 0 && (
              <div className="mb-4 flex items-center gap-3 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3">
                <span className="text-sm font-medium text-sky-700">{selectedIds.size} selected</span>
                <div className="ml-auto flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      void bulkAction.mutateAsync({ lead_ids: [...selectedIds], action: 'stop' })
                      setSelectedIds(new Set())
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-white px-3 py-1.5 text-xs font-medium text-amber-700 hover:bg-amber-50"
                  >
                    <StopCircle size={13} /> Stop
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void bulkAction.mutateAsync({ lead_ids: [...selectedIds], action: 'requeue' })
                      setSelectedIds(new Set())
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-white px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
                  >
                    <RotateCcw size={13} /> Re-activate
                  </button>
                  <select
                    aria-label="Move selected leads to campaign"
                    value={bulkTarget}
                    onChange={(e) => {
                      if (e.target.value) {
                        void bulkAction.mutateAsync({ lead_ids: [...selectedIds], action: 'move_campaign', target_campaign_id: e.target.value })
                        setSelectedIds(new Set())
                        setBulkTarget('')
                      }
                    }}
                    className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-700 outline-none"
                  >
                    <option value="">Move to campaign...</option>
                    {(campaignsQuery.data || []).filter((c) => c.id !== campaignId).map((c) => (
                      <option key={c.id} value={c.id}>{c.name}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => {
                      if (window.confirm(`Delete ${selectedIds.size} leads permanently?`)) {
                        void bulkAction.mutateAsync({ lead_ids: [...selectedIds], action: 'delete' })
                        setSelectedIds(new Set())
                      }
                    }}
                    className="flex items-center gap-1.5 rounded-lg border border-rose-200 bg-white px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50"
                  >
                    <Trash2 size={13} /> Delete
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedIds(new Set())}
                    className="ml-2 text-xs text-slate-400 hover:text-slate-600"
                  >
                    Clear
                  </button>
                </div>
              </div>
            )}

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

      {showAddModal && campaignId && (
        <AddLeadModal
          campaignId={campaignId}
          onClose={() => setShowAddModal(false)}
          onCreate={createLead}
        />
      )}
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
  const [extraExpanded, setExtraExpanded] = useState(false)
  const open = !!leadId
  const lead = query.data

  if (!open) return null

  const hasExtraData = lead?.extra_data && Object.keys(lead.extra_data).length > 0

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
              <a href={lead.linkedin_url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1.5 text-sm text-sky-600 hover:text-sky-700">
                <ExternalLink size={13} /> Open LinkedIn profile
              </a>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {lead?.status && <Badge label={lead.status} asStatus />}
              {lead?.source && <SourceBadge source={lead.source} />}
              {lead?.tags?.map((t) => (
                <span key={t} className="rounded-full bg-sky-100 px-2.5 py-0.5 text-xs font-medium text-sky-700">{t}</span>
              ))}
            </div>
          </div>
          <button type="button" aria-label="Close lead profile" onClick={onClose} className="rounded-lg border border-slate-200 p-2 text-slate-500 hover:bg-slate-50">
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
              {/* Contact */}
              <DrawerSection title="Contact">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Detail label="Email" value={lead.email || '—'} />
                  <Detail label="Phone" value={lead.phone || '—'} />
                  {lead.instagram_username && (
                    <Detail label="Instagram" value={`@${lead.instagram_username}`} />
                  )}
                  {lead.telegram_username && (
                    <Detail label="Telegram" value={`@${lead.telegram_username}`} />
                  )}
                </div>
              </DrawerSection>

              {/* Profile */}
              <DrawerSection title="Profile">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Detail label="Headline" value={lead.headline || '—'} />
                  <Detail label="Company" value={lead.company || '—'} />
                  <Detail label="Location" value={lead.location || '—'} />
                  {lead.linkedin_distance && (
                    <Detail label="LinkedIn distance" value={lead.linkedin_distance} />
                  )}
                </div>
              </DrawerSection>

              {/* Reply intel */}
              {(lead.last_reply_text || lead.last_reply_category) && (
                <DrawerSection title="Reply Intel">
                  <div className="space-y-3">
                    {lead.last_reply_category && (
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-slate-500">Category:</span>
                        <Badge label={lead.last_reply_category} variant="info" />
                        {lead.last_reply_confidence != null && (
                          <span className="text-xs text-slate-400">{Math.round(lead.last_reply_confidence * 100)}% confidence</span>
                        )}
                      </div>
                    )}
                    {lead.last_reply_text && (
                      <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm italic text-slate-600">
                        &ldquo;{lead.last_reply_text}&rdquo;
                      </div>
                    )}
                    {lead.last_reply_at && (
                      <p className="text-xs text-slate-400">Received {formatDate(lead.last_reply_at)}</p>
                    )}
                  </div>
                </DrawerSection>
              )}

              {/* Enrichment data */}
              {hasExtraData && (
                <DrawerSection title="Enrichment Data">
                  <button
                    type="button"
                    onClick={() => setExtraExpanded((v) => !v)}
                    className="text-xs text-sky-600 hover:text-sky-700"
                  >
                    {extraExpanded ? 'Collapse ↑' : 'Expand ↓'}
                  </button>
                  {extraExpanded && (
                    <div className="mt-3 grid gap-2 sm:grid-cols-2">
                      {Object.entries(lead.extra_data!).filter(([, v]) => v != null && v !== '').map(([k, v]) => (
                        <Detail key={k} label={k} value={String(v)} />
                      ))}
                    </div>
                  )}
                </DrawerSection>
              )}

              {/* Outreach timestamps */}
              <DrawerSection title="Outreach Timestamps">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Detail label="Invited" value={formatDate(lead.invited_at)} />
                  <Detail label="Accepted" value={formatDate(lead.accepted_at)} />
                  <Detail label="Replied" value={formatDate(lead.replied_at)} />
                  <Detail label="Stopped" value={formatDate(lead.stopped_at)} />
                  {lead.profile_viewed_at && (
                    <Detail label="Profile viewed" value={formatDate(lead.profile_viewed_at)} />
                  )}
                  <Detail label="Created" value={formatDate(lead.created_at)} />
                </div>
              </DrawerSection>

              {/* Timeline */}
              <DrawerSection title="Timeline">
                <div className="space-y-3">
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
              </DrawerSection>
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

function DrawerSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{title}</h3>
      {children}
    </section>
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

interface AddLeadModalProps {
  campaignId: string
  onClose: () => void
  onCreate: ReturnType<typeof useCreateLead>
}

function AddLeadModal({ campaignId, onClose, onCreate }: AddLeadModalProps) {
  const [form, setForm] = useState<LeadImportPayload>({
    linkedin_url: '',
    email: '',
    phone: '',
    location: '',
    first_name: '',
    last_name: '',
    company: '',
    headline: '',
    source: 'manual',
  })
  const [error, setError] = useState<string | null>(null)

  function set(field: keyof LeadImportPayload, value: string) {
    setForm((prev) => ({ ...prev, [field]: value || null }))
    setError(null)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.linkedin_url && !form.email && !form.phone) {
      setError('At least one of LinkedIn URL, Email, or Phone is required.')
      return
    }
    const payload: LeadImportPayload = {}
    for (const [k, v] of Object.entries(form)) {
      if (v) (payload as Record<string, string>)[k] = v as string
    }
    onCreate.mutate(
      { campaignId, lead: payload },
      {
        onSuccess: () => onClose(),
        onError: (err: unknown) => {
          const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
          setError(msg ?? 'Failed to add lead. They may already exist in this campaign.')
        },
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-8 shadow-2xl">
        <div className="mb-6 flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-sky-500">Add Lead</p>
            <h2 className="mt-1.5 text-xl font-semibold text-slate-900">Add a lead manually</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg border border-slate-200 p-2 text-slate-400 hover:bg-slate-50">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="First name" value={form.first_name ?? ''} onChange={(v) => set('first_name', v)} />
            <FormField label="Last name" value={form.last_name ?? ''} onChange={(v) => set('last_name', v)} />
            <FormField label="LinkedIn URL" value={form.linkedin_url ?? ''} onChange={(v) => set('linkedin_url', v)} placeholder="https://linkedin.com/in/..." className="sm:col-span-2" />
            <FormField label="Email" value={form.email ?? ''} onChange={(v) => set('email', v)} type="email" className="sm:col-span-2" />
            <FormField label="Phone" value={form.phone ?? ''} onChange={(v) => set('phone', v)} />
            <FormField label="Location" value={form.location ?? ''} onChange={(v) => set('location', v)} />
            <FormField label="Company" value={form.company ?? ''} onChange={(v) => set('company', v)} />
            <FormField label="Headline / Title" value={form.headline ?? ''} onChange={(v) => set('headline', v)} />
          </div>

          {error && (
            <p className="rounded-xl border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>
          )}

          <div className="flex justify-end gap-3 pt-2">
            <button type="button" onClick={onClose} className="rounded-2xl border border-slate-200 px-5 py-2.5 text-sm font-medium text-slate-600 hover:bg-slate-50">
              Cancel
            </button>
            <button
              type="submit"
              disabled={onCreate.isPending}
              className="rounded-2xl bg-sky-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-50"
            >
              {onCreate.isPending ? 'Adding…' : 'Add Lead'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function FormField({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
  className,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
  className?: string
}) {
  return (
    <div className={className}>
      <label className="mb-1.5 block text-xs font-medium text-slate-600">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-800 outline-none placeholder:text-slate-400 focus:border-sky-400 focus:ring-2 focus:ring-sky-100"
      />
    </div>
  )
}
