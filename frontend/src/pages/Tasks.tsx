import { useQuery } from '@tanstack/react-query'
import { ListTodo, CheckSquare, Clock } from 'lucide-react'
import { events } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { timeAgo } from '../lib/format'

export default function Tasks() {
  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: () => events.list({ event_type: 'task.', limit: 200 }),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Tasks"
        eyebrow="Engage"
        title="Tasks"
        description="Your daily worklist — calls, follow-ups, and to-dos created by workflows and CRM nodes."
      />

      {isLoading ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-14 skeleton rounded-xl" />)}</div>
      ) : tasks.length === 0 ? (
        <Card><EmptyState icon={ListTodo} title="No tasks yet" description="When a crm.create_task node fires, the task lands in your queue here." /></Card>
      ) : (
        <Card padding="none">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {tasks.map((t) => (
              <li key={t.id} className="flex items-center gap-3 px-4 py-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-50 text-brand-600 dark:bg-brand-900/30">
                  <CheckSquare size={15} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
                    {(t.payload.title_template as string) ?? 'Task'}
                  </p>
                  <p className="flex items-center gap-1 text-[11px] text-slate-400"><Clock size={10} />{timeAgo(t.occurred_at)}</p>
                </div>
                {t.payload.priority ? <Badge label={String(t.payload.priority)} variant="neutral" size="xs" /> : null}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
