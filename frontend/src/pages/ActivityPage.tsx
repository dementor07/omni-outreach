import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity as ActivityIcon } from 'lucide-react'
import { events } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, SearchInput } from '../components/FilterBar'
import { timeAgo } from '../lib/format'

type BadgeVariant = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'info' | 'violet'

// Human-readable labels + tone for the raw event_type stream. Unknown events
// fall back to a humanized form of the type so the feed never shows raw enums.
const EVENT_META: Record<string, { label: string; variant: BadgeVariant }> = {
  'lead.converted': { label: 'Lead converted', variant: 'success' },
  'lead.created': { label: 'Lead created', variant: 'brand' },
  'lead.goal_reached': { label: 'Goal reached', variant: 'success' },
  'lead.sequence_ended': { label: 'Sequence ended', variant: 'neutral' },
  'contact.created': { label: 'Contact added', variant: 'brand' },
  'company.created': { label: 'Company added', variant: 'brand' },
  'deal.created': { label: 'Deal created', variant: 'info' },
  'message.received': { label: 'Reply received', variant: 'violet' },
  'message.sent': { label: 'Message sent', variant: 'info' },
  'approval.requested': { label: 'Approval requested', variant: 'warning' },
  'approval.resolved': { label: 'Approval resolved', variant: 'success' },
  'ai.score.completed': { label: 'Lead scored', variant: 'violet' },
  'pipeline.metric': { label: 'Source run', variant: 'neutral' },
}

function humanize(eventType: string): string {
  return eventType.replace(/[._]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function eventMeta(eventType: string): { label: string; variant: BadgeVariant } {
  return EVENT_META[eventType] ?? { label: humanize(eventType), variant: 'neutral' }
}

export default function ActivityPage() {
  const [entityType, setEntityType] = useState('')
  const { data: items = [], isLoading } = useQuery({
    queryKey: ['activity', entityType],
    queryFn: () => events.list({ entity_type: entityType || undefined, limit: 200 }),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Activity"
        eyebrow="Intelligence"
        title="Activity"
        description="A live tail of every event across your workspace — the system's full audit trail."
      />

      <FilterBar>
        <SearchInput placeholder="Filter by entity type (contact, deal, lead, message…)" value={entityType} onChange={setEntityType} />
      </FilterBar>

      {isLoading ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-12 skeleton rounded-lg" />)}</div>
      ) : items.length === 0 ? (
        <Card><EmptyState icon={ActivityIcon} title="No activity" description="Events stream in here as soon as anything happens." /></Card>
      ) : (
        <Card padding="none">
          <ol className="relative space-y-0 divide-y divide-slate-100 dark:divide-slate-800">
            {items.map((e) => {
              const meta = eventMeta(e.event_type)
              return (
                <li key={e.id} className="flex items-center gap-3 px-4 py-2.5">
                  <Badge label={meta.label} variant={meta.variant} size="xs" />
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    {e.entity_type}{e.entity_id ? ` · ${e.entity_id.slice(0, 8)}` : ''}
                  </span>
                  <span className="ml-auto text-[11px] tabular-nums text-slate-400">{timeAgo(e.occurred_at)}</span>
                </li>
              )
            })}
          </ol>
        </Card>
      )}
    </div>
  )
}
