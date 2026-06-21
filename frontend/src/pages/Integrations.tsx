import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2, ArrowLeft, ExternalLink, ChevronDown, ChevronUp, RefreshCw, Plus, Settings, Play, Pause } from 'lucide-react'
import { integrations, type Connection, type SendingAccount, type SendingAccountStatus, type SendingAccountUpdate, type SendChannelKind } from '../api/v2'
import {
  PROVIDERS, CATEGORY_LABEL, providerSpec, type ProviderSpec, type ProviderCategory,
} from '../utils/providerCatalog'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import { useToast } from '../components/Toast'
import Select from '../components/Select'

const CATEGORY_ORDER: ProviderCategory[] = ['ai', 'email', 'messaging', 'social', 'voice', 'data']

export default function Integrations() {
  const qc = useQueryClient()
  const { data: connections = [], isLoading } = useQuery({
    queryKey: ['connections'],
    queryFn: () => integrations.list(),
  })

  // Which provider is mid-connect (null = browsing the catalog grid).
  const [connecting, setConnecting] = useState<ProviderSpec | null>(null)

  const removeMut = useMutation({
    mutationFn: integrations.remove,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })

  // provider id → its live connections (a provider can have more than one).
  const byProvider = useMemo(() => {
    const map = new Map<string, Connection[]>()
    for (const c of connections) {
      const list = map.get(c.provider) ?? []
      list.push(c)
      map.set(c.provider, list)
    }
    return map
  }, [connections])

  if (connecting) {
    return (
      <ConnectFlow
        spec={connecting}
        onBack={() => setConnecting(null)}
        onDone={() => {
          setConnecting(null)
          qc.invalidateQueries({ queryKey: ['connections'] })
        }}
      />
    )
  }

  const grouped = CATEGORY_ORDER.map((cat) => ({
    cat,
    items: PROVIDERS.filter((p) => p.category === cat),
  })).filter((g) => g.items.length > 0)

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Setup"
        title="Integrations"
        description="Connect the providers Omni talks to. Credentials are encrypted at rest and never leave the server."
      />

      {grouped.map(({ cat, items }) => (
        <section key={cat} className="space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500">{CATEGORY_LABEL[cat]}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((spec) => (
              <ProviderTile
                key={spec.id}
                spec={spec}
                connections={byProvider.get(spec.id) ?? []}
                loading={isLoading}
                onConnect={() => setConnecting(spec)}
                onRemove={(id) => removeMut.mutate(id)}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

function ProviderTile({
  spec, connections, loading, onConnect, onRemove,
}: {
  spec: ProviderSpec
  connections: Connection[]
  loading: boolean
  onConnect: () => void
  onRemove: (id: string) => void
}) {
  const Icon = spec.icon
  const connected = connections.length > 0
  return (
    <Card padding="md" className="flex flex-col">
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
          <Icon size={16} />
        </span>
        {!loading && (
          <Badge
            label={connected ? 'connected' : 'not connected'}
            variant={connected ? 'success' : 'neutral'}
            size="xs"
            dot
          />
        )}
      </div>
      <p className="mt-3 text-sm font-semibold text-slate-900 dark:text-white">{spec.name}</p>
      <p className="mt-0.5 line-clamp-2 text-xs text-slate-500">{spec.blurb}</p>

      {connected && (
        <ul className="mt-3 space-y-1 border-t border-slate-100 pt-3 dark:border-slate-800">
          {connections.map((c) => (
            <ConnectionRow key={c.id} connection={c} onRemove={() => onRemove(c.id)} />
          ))}
        </ul>
      )}

      <div className="mt-3 flex-1" />
      {spec.oauth ? (
        <p className="mt-1 text-[11px] text-slate-400">
          OAuth provider — connect from <span className="font-medium">Settings → Account</span>.
        </p>
      ) : (
        <Button variant={connected ? 'ghost' : 'primary'} size="sm" className="mt-1 w-full" onClick={onConnect}>
          {connected ? 'Add another' : 'Connect'}
        </Button>
      )}
    </Card>
  )
}

function defaultName(spec: ProviderSpec): string {
  return `${spec.name} key`
}

function ConnectFlow({ spec, onBack, onDone }: { spec: ProviderSpec; onBack: () => void; onDone: () => void }) {
  const Icon = spec.icon
  const [name, setName] = useState(defaultName(spec))
  const [values, setValues] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  function setField(key: string, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }))
  }

  const requiredMissing = spec.fields.some((f) => !f.optional && !values[f.key]?.trim())

  const createMut = useMutation({
    mutationFn: async () => {
      // Split typed fields into encrypted credentials vs non-secret metadata.
      const credentials: Record<string, string> = {}
      const metadata: Record<string, string> = {}
      for (const f of spec.fields) {
        const raw = values[f.key]?.trim()
        if (!raw) continue
        ;(f.metadata ? metadata : credentials)[f.key] = raw
      }
      return integrations.create({ provider: spec.id, name: name.trim() || defaultName(spec), credentials, metadata })
    },
    onSuccess: onDone,
    onError: (e: unknown) => setError(e instanceof Error ? e.message : 'Failed to connect'),
  })

  return (
    <div className="space-y-6">
      <button type="button" onClick={onBack} className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft size={15} /> All integrations
      </button>

      <Card padding="lg" className="mx-auto max-w-lg space-y-4">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
            <Icon size={20} />
          </span>
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-white">Connect {spec.name}</h2>
            <p className="text-xs text-slate-500">{spec.blurb}</p>
          </div>
        </div>

        <div className="space-y-3">
          {spec.fields.map((f) => (
            <label key={f.key} className="block">
              <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                {f.label}
                {f.optional && <span className="ml-1 normal-case text-slate-400">(optional)</span>}
              </span>
              <input
                type={f.type === 'secret' ? 'password' : f.type === 'number' ? 'number' : 'text'}
                value={values[f.key] ?? ''}
                onChange={(e) => setField(f.key, e.target.value)}
                placeholder={f.placeholder}
                autoComplete="off"
                className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800"
              />
            </label>
          ))}

          <label className="block">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Label <span className="ml-1 normal-case text-slate-400">(so you can tell connections apart)</span>
            </span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"
            />
          </label>
        </div>

        {spec.docsUrl && (
          <a
            href={spec.docsUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-brand-600 hover:underline"
          >
            <ExternalLink size={12} /> Where do I find this?
          </a>
        )}

        {error && <p className="rounded-md bg-rose-50 px-3 py-2 text-xs text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">{error}</p>}

        <div className="flex justify-end gap-2 border-t border-slate-100 pt-4 dark:border-slate-800">
          <Button variant="ghost" onClick={onBack}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => createMut.mutate()}
            isLoading={createMut.isPending}
            disabled={requiredMissing}
          >
            Connect {spec.name}
          </Button>
        </div>
      </Card>
    </div>
  )
}

// Kept exported in case a node-config surface wants to resolve a provider spec.
export { providerSpec }


function ConnectionRow({ connection, onRemove }: { connection: Connection; onRemove: () => void }) {
  const [expanded, setExpanded] = useState(false)
  const qc = useQueryClient()
  const toast = useToast()
  
  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ['integrations', connection.id, 'accounts'],
    queryFn: () => integrations.accounts(connection.id),
    enabled: expanded,
  })

  const syncMut = useMutation({
    mutationFn: () => integrations.syncAccounts(connection.id),
    onSuccess: (res) => {
      toast.success(`Synced ${res.synced} accounts`)
      qc.invalidateQueries({ queryKey: ['integrations', connection.id, 'accounts'] })
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : 'Sync failed')
  })

  const [adding, setAdding] = useState(false)

  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-2 text-xs">
        <button type="button" onClick={() => setExpanded(!expanded)} className="flex min-w-0 flex-1 items-center gap-1.5 text-left text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
          {expanded ? <ChevronUp size={14} className="shrink-0" /> : <ChevronDown size={14} className="shrink-0" />}
          <span className="truncate font-medium">{connection.name}</span>
        </button>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onRemove}
            className="shrink-0 rounded p-1 text-slate-400 hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/40"
            aria-label={`Disconnect ${connection.name}`}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>
      
      {expanded && (
        <div className="ml-5 mt-1 space-y-2 rounded-lg border border-slate-100 bg-slate-50 p-2 dark:border-slate-800 dark:bg-slate-900/50">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Accounts</span>
            <div className="flex gap-1">
              {connection.provider === 'unipile' && (
                <Button variant="secondary" size="xs" onClick={() => syncMut.mutate()} isLoading={syncMut.isPending} icon={RefreshCw}>
                  Sync
                </Button>
              )}
              <Button variant="secondary" size="xs" onClick={() => setAdding(!adding)} icon={Plus}>
                Add
              </Button>
            </div>
          </div>
          
          {adding && (
            <AddAccountForm 
              connectionId={connection.id} 
              onDone={() => setAdding(false)} 
              defaultKind={connection.provider === 'unipile' ? 'linkedin' : 'email'} 
            />
          )}

          {isLoading && <div className="text-xs text-slate-400">Loading accounts...</div>}
          {!isLoading && accounts.length === 0 && !adding && (
            <div className="text-xs text-slate-400">No accounts found.</div>
          )}
          
          <div className="space-y-1">
            {accounts.map(acc => (
              <AccountRow key={acc.id} account={acc} connectionId={connection.id} />
            ))}
          </div>
        </div>
      )}
    </li>
  )
}

function AccountRow({ account, connectionId }: { account: SendingAccount; connectionId: string }) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draftCap, setDraftCap] = useState(String(account.daily_cap))
  const [draftStatus, setDraftStatus] = useState<SendingAccountStatus>(account.status)

  const updateMut = useMutation({
    mutationFn: (body: SendingAccountUpdate) => integrations.updateAccount(account.id, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations', connectionId, 'accounts'] })
      setEditing(false)
    }
  })

  const delMut = useMutation({
    mutationFn: () => integrations.removeAccount(account.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['integrations', connectionId, 'accounts'] })
  })

  const active = account.status === 'active'
  const banned = account.status === 'banned'
  const warming = account.status === 'warming'

  const togglePause = () => {
    updateMut.mutate({ status: active ? 'paused' : 'active' })
  }

  if (editing) {
    return (
      <div className="flex items-center gap-2 rounded bg-white p-1.5 shadow-sm dark:bg-slate-800 text-xs">
        <input 
          type="number" 
          value={draftCap} 
          onChange={e => setDraftCap(e.target.value)} 
          className="w-16 rounded border border-slate-200 px-1 py-0.5 dark:border-slate-700 dark:bg-slate-900" 
          placeholder="Cap"
        />
        <Select 
          value={draftStatus} 
          onChange={v => setDraftStatus(v as SendingAccountStatus)}
          options={[
            { value: 'active', label: 'Active' },
            { value: 'paused', label: 'Paused' },
            { value: 'warming', label: 'Warming' },
            { value: 'banned', label: 'Banned' },
          ]}
        />
        <Button variant="primary" size="xs" onClick={() => updateMut.mutate({ daily_cap: parseInt(draftCap, 10) || 0, status: draftStatus })} isLoading={updateMut.isPending}>Save</Button>
        <Button variant="ghost" size="xs" onClick={() => setEditing(false)}>Cancel</Button>
      </div>
    )
  }

  return (
    <div className="group flex items-center justify-between rounded px-1.5 py-1 hover:bg-slate-100 dark:hover:bg-slate-800/80">
      <div className="flex items-center gap-2 min-w-0">
        <Badge 
          label={account.status} 
          variant={active ? 'success' : banned ? 'danger' : warming ? 'warning' : 'neutral'} 
          size="xs" 
        />
        <span className="truncate text-xs font-medium text-slate-700 dark:text-slate-200" title={account.external_identity}>
          {account.display_name || account.external_identity}
        </span>
        <span className="text-[10px] text-slate-400">
          {account.sends_today}/{account.daily_cap === 0 ? '∞' : account.daily_cap} today
        </span>
      </div>
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button type="button" onClick={togglePause} className="p-1 text-slate-400 hover:text-slate-700 dark:hover:text-slate-200" title={active ? "Pause" : "Resume"}>
          {active ? <Pause size={12} /> : <Play size={12} />}
        </button>
        <button type="button" onClick={() => setEditing(true)} className="p-1 text-slate-400 hover:text-brand-600" title="Edit">
          <Settings size={12} />
        </button>
        <button type="button" onClick={() => { if(confirm('Remove account?')) delMut.mutate() }} className="p-1 text-slate-400 hover:text-rose-600" title="Remove">
          <Trash2 size={12} />
        </button>
      </div>
    </div>
  )
}

function AddAccountForm({ connectionId, onDone, defaultKind }: { connectionId: string; onDone: () => void; defaultKind: SendChannelKind }) {
  const qc = useQueryClient()
  const [kind, setKind] = useState<SendChannelKind>(defaultKind)
  const [extId, setExtId] = useState('')
  const [name, setName] = useState('')
  const [cap, setCap] = useState('')

  const mut = useMutation({
    mutationFn: () => integrations.addAccount(connectionId, {
      channel_kind: kind,
      external_identity: extId,
      display_name: name || null,
      daily_cap: parseInt(cap, 10) || 0,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations', connectionId, 'accounts'] })
      onDone()
    }
  })

  return (
    <div className="mb-2 space-y-2 rounded border border-slate-200 bg-white p-2 shadow-sm dark:border-slate-700 dark:bg-slate-800 text-xs">
      <div className="grid grid-cols-2 gap-2">
        <input 
          placeholder="Identity (e.g. email)" 
          value={extId} 
          onChange={e => setExtId(e.target.value)}
          className="rounded border border-slate-200 px-2 py-1 dark:border-slate-700 dark:bg-slate-900"
        />
        <input 
          placeholder="Display name" 
          value={name} 
          onChange={e => setName(e.target.value)}
          className="rounded border border-slate-200 px-2 py-1 dark:border-slate-700 dark:bg-slate-900"
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Select 
          value={kind}
          onChange={v => setKind(v as SendChannelKind)}
          options={[
            {value: 'email', label: 'Email'},
            {value: 'linkedin', label: 'LinkedIn'},
            {value: 'sms', label: 'SMS'},
            {value: 'voice', label: 'Voice'},
            {value: 'whatsapp', label: 'WhatsApp'},
            {value: 'instagram', label: 'Instagram'},
            {value: 'telegram', label: 'Telegram'},
          ]}
        />
        <input 
          type="number" 
          placeholder="Daily cap (0=unlimited)" 
          value={cap} 
          onChange={e => setCap(e.target.value)}
          className="rounded border border-slate-200 px-2 py-1 dark:border-slate-700 dark:bg-slate-900"
        />
      </div>
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" size="xs" onClick={onDone}>Cancel</Button>
        <Button variant="primary" size="xs" disabled={!extId} onClick={() => mut.mutate()} isLoading={mut.isPending}>Add</Button>
      </div>
    </div>
  )
}
