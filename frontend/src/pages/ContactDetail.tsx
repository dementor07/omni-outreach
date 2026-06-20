import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Mail, Phone, Building2, Linkedin, Clock, Briefcase, DollarSign, GitBranch } from 'lucide-react'
import { projections, events, inbox, canvas, type Contact, type OmniEvent, type Deal } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card, { CardHeader } from '../components/Card'
import Avatar from '../components/Avatar'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { fullName, timeAgo } from '../lib/format'
import { eventLabel } from '../utils/nodeLabel'

export default function ContactDetail() {
  const { id } = useParams<{ id: string }>()
  const contactQ = useQuery({
    queryKey: ['contact', id],
    queryFn: () => projections.contact(id!),
    enabled: !!id,
  })
  const timelineQ = useQuery({
    queryKey: ['contact-events', id],
    queryFn: () => events.list({ entity_id: id, limit: 100 }),
    enabled: !!id,
  })
  const threadQ = useQuery({
    queryKey: ['inbox-thread', id],
    queryFn: () => inbox.thread(id!),
    enabled: !!id,
  })
  // Deals + leads + campaigns aren't per-contact endpoints, so derive from the
  // workspace lists (small in practice) filtered to this contact.
  const dealsQ = useQuery({ queryKey: ['deals'], queryFn: () => projections.deals({ limit: 500 }) })
  const leadsQ = useQuery({ queryKey: ['leads'], queryFn: () => projections.leads({ limit: 1000 }) })
  const campaignsQ = useQuery({ queryKey: ['campaigns-list'], queryFn: canvas.list })

  const contact = contactQ.data
  const deals = (dealsQ.data ?? []).filter((d) => d.contact_id === id)
  const myLeads = (leadsQ.data ?? []).filter((l) => l.contact_id === id)
  const campaignName = new Map((campaignsQ.data ?? []).map((w) => [w.id, w.name]))
  const campaignIds = Array.from(new Set(myLeads.map((l) => l.workflow_id).filter(Boolean))) as string[]

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="CRM · Contact"
        title={contact ? fullName(contact) || contact.email || 'Contact' : 'Contact'}
        description={contact?.headline ?? undefined}
        actions={
          <Link to="/contacts" className="inline-flex h-9 items-center gap-2 rounded-lg px-3.5 text-sm font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800">
            <ArrowLeft size={15} /> Back to contacts
          </Link>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
        {/* Left rail: profile + campaigns + deals */}
        <div className="space-y-4">
          <Card padding="lg">
            {contactQ.isLoading ? (
              <div className="h-32 skeleton rounded-xl" />
            ) : !contact ? (
              <EmptyState title="Contact not found" />
            ) : (
              <ContactProfile contact={contact} dealCount={deals.length} campaignCount={campaignIds.length} />
            )}
          </Card>

          <Card padding="lg">
            <CardHeader title="Campaigns" description={campaignIds.length ? `In ${campaignIds.length} campaign${campaignIds.length === 1 ? '' : 's'}` : 'Not in any campaign'} />
            {campaignIds.length === 0 ? (
              <EmptyState icon={GitBranch} title="No campaigns" description="This contact isn't enrolled in any campaign yet." />
            ) : (
              <ul className="space-y-1.5">
                {campaignIds.map((wid) => (
                  <li key={wid}>
                    <Link to={`/campaigns/${wid}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800">
                      <GitBranch size={14} className="text-brand-500" />
                      <span className="truncate">{campaignName.get(wid) ?? 'Campaign'}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card padding="lg">
            <CardHeader title="Deals" description={deals.length ? `${deals.length} deal${deals.length === 1 ? '' : 's'}` : 'No deals'} />
            {deals.length === 0 ? (
              <EmptyState icon={DollarSign} title="No deals" description="Deals linked to this contact will appear here." />
            ) : (
              <ul className="space-y-2">
                {deals.map((d) => <DealRow key={d.id} deal={d} />)}
              </ul>
            )}
          </Card>
        </div>

        {/* Right: conversation + activity */}
        <div className="space-y-4">
          <Card padding="lg">
            <CardHeader title="Conversation" description={`${threadQ.data?.length ?? 0} messages`} />
            {threadQ.isLoading ? (
              <div className="space-y-2">{[0, 1].map((i) => <div key={i} className="h-12 skeleton rounded-xl" />)}</div>
            ) : (threadQ.data?.length ?? 0) === 0 ? (
              <EmptyState title="No messages" description="Replies and sends will appear here." />
            ) : (
              <div className="space-y-3">
                {threadQ.data?.map((m) => (
                  <div key={m.id} className={`rounded-2xl px-4 py-2.5 text-sm ${m.direction === 'outbound' ? 'ml-8 bg-brand-50 dark:bg-brand-900/20' : 'mr-8 bg-slate-50 dark:bg-slate-800/60'}`}>
                    {m.subject && <p className="text-xs font-semibold text-slate-500">{m.subject}</p>}
                    <p className="whitespace-pre-wrap text-slate-700 dark:text-slate-200">{m.body ?? ''}</p>
                    <p className="mt-1.5 text-[10px] text-slate-400">{m.channel} · {timeAgo(m.occurred_at)}</p>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card padding="lg">
            <CardHeader title="Activity timeline" description="Every event for this contact" />
            {timelineQ.isLoading ? (
              <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-8 skeleton rounded-lg" />)}</div>
            ) : (timelineQ.data?.length ?? 0) === 0 ? (
              <EmptyState icon={Clock} title="No activity yet" description="Events for this contact will stream in here." />
            ) : (
              <Timeline events={timelineQ.data ?? []} />
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}

function ContactProfile({ contact, dealCount, campaignCount }: { contact: Contact; dealCount: number; campaignCount: number }) {
  return (
    <div>
      <div className="flex flex-col items-center text-center">
        <Avatar name={fullName(contact) || contact.email || 'Unknown'} size={64} />
        <p className="mt-3 text-base font-semibold text-slate-900 dark:text-white">{fullName(contact) || '—'}</p>
        {contact.headline && <p className="mt-0.5 text-sm text-slate-500">{contact.headline}</p>}
        {contact.source && <div className="mt-2"><Badge label={contact.source} variant="neutral" size="xs" /></div>}
      </div>
      <div className="mt-4 flex justify-center gap-4 border-y border-slate-100 py-3 text-center dark:border-slate-800">
        <div>
          <p className="text-lg font-bold text-slate-900 dark:text-white">{campaignCount}</p>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Campaigns</p>
        </div>
        <div>
          <p className="text-lg font-bold text-slate-900 dark:text-white">{dealCount}</p>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Deals</p>
        </div>
      </div>
      <div className="mt-4 space-y-2.5 text-sm">
        {contact.email && <Field icon={Mail} label="Email" value={contact.email} href={`mailto:${contact.email}`} />}
        {contact.phone && <Field icon={Phone} label="Phone" value={contact.phone} />}
        {contact.company && <Field icon={Building2} label="Company" value={contact.company} />}
        {contact.linkedin_url && (
          <Field icon={Linkedin} label="LinkedIn" value={contact.linkedin_url} href={contact.linkedin_url} />
        )}
      </div>
    </div>
  )
}

function DealRow({ deal }: { deal: Deal }) {
  return (
    <li className="flex items-center justify-between gap-2 rounded-lg border border-slate-100 px-3 py-2 dark:border-slate-800">
      <div className="flex min-w-0 items-center gap-2">
        <Briefcase size={14} className="shrink-0 text-indigo-500" />
        <span className="truncate text-sm text-slate-700 dark:text-slate-200">{deal.name}</span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {deal.value != null && (
          <span className="text-xs font-semibold tabular-nums text-slate-600 dark:text-slate-300">
            {deal.currency} {Number(deal.value).toLocaleString()}
          </span>
        )}
        <Badge label={deal.stage} variant="neutral" size="xs" />
      </div>
    </li>
  )
}

function Field({ icon: Icon, label, value, href }: { icon: React.ElementType; label: string; value: string; href?: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <Icon size={14} className="mt-0.5 flex-shrink-0 text-slate-400" />
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
        {href ? (
          <a href={href} target="_blank" rel="noreferrer" className="block truncate text-brand-600 hover:underline">{value}</a>
        ) : (
          <p className="truncate text-slate-700 dark:text-slate-200">{value}</p>
        )}
      </div>
    </div>
  )
}

// A short, human summary of an event's payload — no raw JSON dumps.
function eventDetail(e: OmniEvent): string | null {
  const p = e.payload || {}
  const pick = (k: string) => (typeof p[k] === 'string' || typeof p[k] === 'number' ? String(p[k]) : null)
  return (
    pick('subject') ?? pick('title_template') ?? pick('intent') ?? pick('new_stage') ??
    pick('channel') ?? pick('reason') ?? pick('error') ?? null
  )
}

function Timeline({ events: evs }: { events: OmniEvent[] }) {
  return (
    <ol className="relative ml-2 space-y-4 border-l border-slate-200 pl-4 dark:border-slate-700">
      {evs.map((e) => {
        const detail = eventDetail(e)
        return (
          <li key={e.id} className="relative">
            <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-brand-400 ring-4 ring-white dark:ring-slate-900" />
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-slate-800 dark:text-slate-100">{eventLabel(e.event_type)}</span>
              <span className="text-[11px] text-slate-400">{timeAgo(e.occurred_at)}</span>
            </div>
            {detail && <p className="mt-0.5 truncate text-xs text-slate-500">{detail}</p>}
          </li>
        )
      })}
    </ol>
  )
}
