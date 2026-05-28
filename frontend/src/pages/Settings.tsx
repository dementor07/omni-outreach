import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Building2, Plus } from 'lucide-react'
import { auth, workspaces } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'

export default function Settings() {
  const qc = useQueryClient()
  const meQ = useQuery({ queryKey: ['me'], queryFn: auth.me })
  const wsQ = useQuery({ queryKey: ['workspaces'], queryFn: workspaces.list })

  const [showNew, setShowNew] = useState(false)
  const [name, setName] = useState('')
  const createMut = useMutation({
    mutationFn: () => workspaces.create(name.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      setName('')
      setShowNew(false)
    },
  })
  const switchMut = useMutation({
    mutationFn: workspaces.switch,
    onSuccess: () => qc.invalidateQueries(),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="Account"
        description="You, your workspaces, and the API surface you're talking to."
      />

      <Card className="p-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Signed in as</p>
        {meQ.isLoading ? (
          <p className="mt-2 text-sm text-slate-500">Loading…</p>
        ) : (
          <p className="mt-2 text-sm font-medium text-slate-900 dark:text-white">{meQ.data?.email}</p>
        )}
      </Card>

      <Card className="p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Workspaces</p>
          <Button size="sm" variant="secondary" icon={Plus} onClick={() => setShowNew((v) => !v)}>
            New workspace
          </Button>
        </div>

        {showNew && (
          <div className="mt-3 flex items-center gap-2">
            <input
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Workspace name"
              className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
            <Button
              variant="primary"
              size="sm"
              onClick={() => createMut.mutate()}
              isLoading={createMut.isPending}
              disabled={!name.trim()}
            >
              Create
            </Button>
          </div>
        )}

        <div className="mt-3 space-y-1.5">
          {wsQ.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            wsQ.data?.map((w) => (
              <div
                key={w.id}
                className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800"
              >
                <div className="flex items-center gap-2 text-sm">
                  <Building2 size={14} className="text-slate-400" />
                  <span className="font-medium text-slate-900 dark:text-white">{w.name}</span>
                  <span className="text-xs text-slate-400">{w.slug}</span>
                </div>
                <Button size="sm" variant="ghost" onClick={() => switchMut.mutate(w.id)}>
                  Switch
                </Button>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  )
}
