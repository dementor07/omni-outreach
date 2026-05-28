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
            {items.map((e) => (
              <li key={e.id} className="flex items-center gap-3 px-4 py-2.5">
                <Badge label={e.event_type} variant="info" size="xs" />
                <span className="text-xs text-slate-600 dark:text-slate-300">{e.entity_type}{e.entity_id ? ` ${e.entity_id.slice(0, 8)}` : ''}</span>
                <span className="ml-auto text-[11px] tabular-nums text-slate-400">{timeAgo(e.occurred_at)}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}
    </div>
  )
}
