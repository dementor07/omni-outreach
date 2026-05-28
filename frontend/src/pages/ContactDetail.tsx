import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Mail, Phone, Building2, Linkedin, Clock } from 'lucide-react'
import { projections, events, inbox, type Contact, type OmniEvent } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card, { CardHeader } from '../components/Card'
import Avatar from '../components/Avatar'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { fullName, timeAgo } from '../lib/format'

export default function ContactDetail() {
  const { id } = useParams<{ id: string }>()
  // The projections API lists contacts; find the one we want from the list.
  const contactsQ = useQuery({ queryKey: ['contacts'], queryFn: () => projections.contacts(500) })
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

  const contact = contactsQ.data?.find((c) => c.id === id)

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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        {/* Profile card */}
        <div className="space-y-4">
          <Card padding="lg">
            {contactsQ.isLoading ? (
              <div className="h-32 skeleton rounded-xl" />
            ) : !contact ? (
              <EmptyState title="Contact not found" />
            ) : (
              <ContactProfile contact={contact} />
            )}
          </Card>
        </div>

        {/* Timeline + messages */}
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

function ContactProfile({ contact }: { contact: Contact }) {
  return (
    <div>
      <div className="flex flex-col items-center text-center">
        <Avatar name={fullName(contact) || contact.email || 'Unknown'} size={64} />
        <p className="mt-3 text-base font-semibold text-slate-900 dark:text-white">{fullName(contact) || '—'}</p>
        {contact.headline && <p className="mt-0.5 text-sm text-slate-500">{contact.headline}</p>}
        {contact.source && <div className="mt-2"><Badge label={contact.source} variant="neutral" size="xs" /></div>}
      </div>
      <div className="mt-5 space-y-2.5 text-sm">
        {contact.email && <Field icon={Mail} label="Email" value={contact.email} />}
        {contact.phone && <Field icon={Phone} label="Phone" value={contact.phone} />}
        {contact.company && <Field icon={Building2} label="Company" value={contact.company} />}
        {contact.linkedin_url && (
          <Field icon={Linkedin} label="LinkedIn" value={contact.linkedin_url} href={contact.linkedin_url} />
        )}
      </div>
    </div>
  )
}

function Field({ icon: Icon, label, value, href }: { icon: React.ElementType; label: string; value: string; href?: string }) {
  return (
    <div className="flex items-start gap-2.5">
      <Icon size={14} className="mt-0.5 flex-shrink-0 text-slate-400" />
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
        {href ? (
          <a href={href} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">{value}</a>
        ) : (
          <p className="truncate text-slate-700 dark:text-slate-200">{value}</p>
        )}
      </div>
    </div>
  )
}

function Timeline({ events: evs }: { events: OmniEvent[] }) {
  return (
    <ol className="relative ml-2 space-y-4 border-l border-slate-200 pl-4 dark:border-slate-700">
      {evs.map((e) => (
        <li key={e.id} className="relative">
          <span className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-brand-400 ring-4 ring-white dark:ring-slate-900" />
          <div className="flex items-center gap-2">
            <Badge label={e.event_type} variant="info" size="xs" />
            <span className="text-[11px] text-slate-400">{timeAgo(e.occurred_at)}</span>
          </div>
          {Object.keys(e.payload).length > 0 && (
            <p className="mt-1 truncate font-mono text-[11px] text-slate-500">{JSON.stringify(e.payload)}</p>
          )}
        </li>
      ))}
    </ol>
  )
}
