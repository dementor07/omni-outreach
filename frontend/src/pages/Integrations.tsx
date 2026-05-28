import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plug, Trash2, Plus } from 'lucide-react'
import { integrations, type Connection } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'

const KNOWN_PROVIDERS = [
  'apollo', 'hunter', 'proxycurl', 'sheets', 'producthunt',
  'anthropic', 'openai', 'mindstudio',
  'smtp', 'twilio', 'unipile', 'slack', 'retell',
] as const

export default function Integrations() {
  const qc = useQueryClient()
  const { data: connections = [], isLoading } = useQuery({
    queryKey: ['connections'],
    queryFn: () => integrations.list(),
  })

  const [showAdd, setShowAdd] = useState(false)
  const removeMut = useMutation({
    mutationFn: integrations.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="System"
        title="Integrations"
        description="API keys and OAuth tokens for every provider. Credentials are encrypted at rest."
        actions={
          <Button variant="primary" icon={Plus} onClick={() => setShowAdd((v) => !v)}>
            Connect provider
          </Button>
        }
      />

      {showAdd && (
        <AddConnection
          onCancel={() => setShowAdd(false)}
          onDone={() => {
            setShowAdd(false)
            qc.invalidateQueries({ queryKey: ['connections'] })
          }}
        />
      )}

      {isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : connections.length === 0 ? (
        <Card>
          <EmptyState
            icon={Plug}
            title="No integrations connected"
            description="Connect a provider above. Every node that hits the network needs a connection."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {connections.map((c) => (
            <ConnectionCard key={c.id} c={c} onRemove={() => removeMut.mutate(c.id)} />
          ))}
        </div>
      )}
    </div>
  )
}

function ConnectionCard({ c, onRemove }: { c: Connection; onRemove: () => void }) {
  return (
    <Card className="flex items-start justify-between gap-3 p-4">
      <div className="min-w-0">
        <Badge variant="info" label={c.provider} />
        <p className="mt-2 truncate text-sm font-semibold text-slate-900 dark:text-white">{c.name}</p>
        <p className="mt-0.5 text-[11px] uppercase tracking-wider text-slate-400">
          Connected {new Date(c.connected_at).toLocaleDateString()}
        </p>
      </div>
      <Button variant="ghost" size="sm" icon={Trash2} onClick={onRemove}>
        Remove
      </Button>
    </Card>
  )
}

function AddConnection({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [provider, setProvider] = useState<string>(KNOWN_PROVIDERS[0])
  const [name, setName] = useState('')
  const [credentialsJson, setCredentialsJson] = useState('{\n  "api_key": ""\n}')
  const [error, setError] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: async () => {
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(credentialsJson)
      } catch {
        throw new Error('Credentials must be valid JSON')
      }
      return integrations.create({ provider, name: name.trim(), credentials: parsed })
    },
    onSuccess: onDone,
    onError: (e: unknown) => setError(e instanceof Error ? e.message : 'Failed'),
  })

  return (
    <Card className="space-y-3 p-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Provider</span>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          >
            {KNOWN_PROVIDERS.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Name (unique per provider)</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Production API key"
            className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
          />
        </label>
      </div>
      <label className="block">
        <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">Credentials JSON</span>
        <textarea
          rows={5}
          value={credentialsJson}
          onChange={(e) => setCredentialsJson(e.target.value)}
          className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs dark:border-slate-700 dark:bg-slate-800"
        />
      </label>
      {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" onClick={() => createMut.mutate()} isLoading={createMut.isPending} disabled={!name.trim()}>
          Connect
        </Button>
      </div>
    </Card>
  )
}
