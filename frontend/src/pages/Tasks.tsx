import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ListTodo, Clock, AlertTriangle } from 'lucide-react'
import { clsx } from 'clsx'
import { projections, type Task } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import { FilterBar, Toggle } from '../components/FilterBar'
import { useToast } from '../components/Toast'

const PRIORITY_TONE: Record<string, 'danger' | 'warning' | 'neutral'> = {
  high: 'danger',
  urgent: 'danger',
  normal: 'neutral',
  low: 'neutral',
}

export default function Tasks() {
  const qc = useQueryClient()
  const toast = useToast()
  const [view, setView] = useState<'open' | 'done' | 'all'>('open')

  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['tasks', view],
    queryFn: () => projections.tasks(view === 'all' ? {} : { status: view }),
  })

  const completeMut = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) => projections.completeTask(id, done),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['tasks'] }), 400),
    onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not update task'),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Tasks"
        eyebrow="Engage"
        title="Tasks"
        description="Your worklist — calls, follow-ups, and to-dos created by workflows and CRM nodes."
      />

      <FilterBar>
        <Toggle
          value={view}
          onChange={(v) => setView(v as typeof view)}
          items={[
            { value: 'open', label: 'Open' },
            { value: 'done', label: 'Done' },
            { value: 'all', label: 'All' },
          ]}
        />
      </FilterBar>

      {isLoading ? (
        <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="h-14 skeleton rounded-xl" />)}</div>
      ) : tasks.length === 0 ? (
        <Card>
          <EmptyState
            icon={ListTodo}
            title={view === 'done' ? 'No completed tasks' : 'No tasks yet'}
            description="When a Create task node fires, the task lands in your queue here."
          />
        </Card>
      ) : (
        <Card padding="none">
          <ul className="divide-y divide-slate-100 dark:divide-slate-800">
            {tasks.map((t) => (
              <TaskRow
                key={t.id}
                task={t}
                busy={completeMut.isPending}
                onToggle={(done) => completeMut.mutate({ id: t.id, done })}
              />
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}

function dueMeta(due: string | null): { label: string; overdue: boolean } | null {
  if (!due) return null
  const d = new Date(due)
  if (Number.isNaN(d.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const overdue = d < today
  return { label: d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }), overdue }
}

function TaskRow({ task, busy, onToggle }: { task: Task; busy: boolean; onToggle: (done: boolean) => void }) {
  const done = task.status === 'done'
  const due = dueMeta(task.due_date)
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      <input
        type="checkbox"
        checked={done}
        disabled={busy}
        onChange={(e) => onToggle(e.target.checked)}
        aria-label={done ? 'Reopen task' : 'Complete task'}
        className="h-4 w-4 shrink-0 cursor-pointer rounded border-slate-300 text-brand-600 focus:ring-brand-500"
      />
      <div className="min-w-0 flex-1">
        <p className={clsx('truncate text-sm font-medium', done ? 'text-slate-400 line-through' : 'text-slate-900 dark:text-white')}>
          {task.title}
        </p>
        <div className="mt-0.5 flex items-center gap-2 text-[11px] text-slate-400">
          {due && (
            <span className={clsx('inline-flex items-center gap-1', due.overdue && !done && 'font-semibold text-rose-500')}>
              {due.overdue && !done ? <AlertTriangle size={10} /> : <Clock size={10} />}
              {due.overdue && !done ? `Overdue · ${due.label}` : `Due ${due.label}`}
            </span>
          )}
          {task.contact_id && (
            <Link to={`/contacts/${task.contact_id}`} className="text-brand-500 hover:underline">
              View contact
            </Link>
          )}
        </div>
      </div>
      {task.priority && task.priority !== 'normal' && (
        <Badge label={task.priority} variant={PRIORITY_TONE[task.priority] ?? 'neutral'} size="xs" />
      )}
    </li>
  )
}
