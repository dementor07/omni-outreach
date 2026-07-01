import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useState } from 'react'
import {
  Building2, Check, Code2, Copy, KeyRound, Moon, Pencil, Plus, Send, Sun, Trash2,
  User, Users as UsersIcon, Webhook,
} from 'lucide-react'
import { clsx } from 'clsx'
import {
  apiKeys, auth, webhookSubscriptions, workspaces, WEBHOOK_EVENT_TYPES,
} from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Button from '../components/Button'
import Badge from '../components/Badge'
import Tabs from '../components/Tabs'
import { useToast } from '../components/Toast'
import { useTheme } from '../hooks/useTheme'

const inputClass =
  'w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white'

function AccountTab() {
  const toast = useToast()
  const meQ = useQuery({ queryKey: ['me'], queryFn: auth.me })

  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const passwordMut = useMutation({
    mutationFn: () => auth.changePassword(current, next),
    onSuccess: () => {
      setCurrent(''); setNext(''); setConfirm('')
      toast.success('Password updated')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not update password'),
  })

  function submitPassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (next !== confirm) {
      toast.error('New passwords do not match')
      return
    }
    passwordMut.mutate()
  }

  return (
    <div className="space-y-6">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <User size={14} className="text-slate-400" />
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Signed in as</p>
        </div>
        {meQ.isLoading ? (
          <p className="mt-2 text-sm text-slate-500">Loading…</p>
        ) : (
          <div className="mt-2 flex items-center gap-2">
            <p className="text-sm font-medium text-slate-900 dark:text-white">{meQ.data?.email}</p>
            {meQ.data?.google_connected && <Badge variant="info" label="Google connected" />}
          </div>
        )}
      </Card>

      <Card className="p-4">
        <div className="flex items-center gap-2">
          <KeyRound size={14} className="text-slate-400" />
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Change password</p>
        </div>
        <form onSubmit={submitPassword} className="mt-3 max-w-sm space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-slate-500">Current password</span>
            <input
              type="password"
              required
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className={clsx('mt-1', inputClass)}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-500">New password (min. 8 characters)</span>
            <input
              type="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              className={clsx('mt-1', inputClass)}
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-500">Confirm new password</span>
            <input
              type="password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={clsx('mt-1', inputClass)}
            />
          </label>
          <Button type="submit" variant="primary" size="sm" isLoading={passwordMut.isPending} disabled={!current || !next || !confirm}>
            Update password
          </Button>
        </form>
      </Card>
    </div>
  )
}

function WorkspaceTab() {
  const qc = useQueryClient()
  const toast = useToast()
  const meQ = useQuery({ queryKey: ['me'], queryFn: auth.me })
  const wsQ = useQuery({ queryKey: ['workspaces'], queryFn: workspaces.list })

  const [showNew, setShowNew] = useState(false)
  const [name, setName] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const roleByWorkspace = new Map((meQ.data?.workspaces ?? []).map((w) => [w.id, w.role]))

  const createMut = useMutation({
    mutationFn: () => workspaces.create(name.trim()),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      qc.invalidateQueries({ queryKey: ['me'] })
      setName('')
      setShowNew(false)
      toast.success('Workspace created')
    },
  })
  // The switch endpoint mints a fresh JWT scoped to the new workspace — it
  // MUST replace the stored token or the switch silently does nothing.
  const switchMut = useMutation({
    mutationFn: workspaces.switch,
    onSuccess: (data) => {
      localStorage.setItem('token', data.access_token)
      qc.invalidateQueries()
      toast.success('Workspace switched')
    },
  })
  const renameMut = useMutation({
    mutationFn: ({ id, newName }: { id: string; newName: string }) => workspaces.rename(id, newName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['workspaces'] })
      qc.invalidateQueries({ queryKey: ['me'] })
      setRenamingId(null)
      toast.success('Workspace renamed')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Rename failed'),
  })

  return (
    <div className="space-y-6">
      <Card className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Building2 size={14} className="text-slate-400" />
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Workspaces</p>
          </div>
          <Button size="sm" variant="secondary" icon={Plus} onClick={() => setShowNew((v) => !v)}>
            New workspace
          </Button>
        </div>

        {showNew && (
          <div className="mt-3 flex items-center gap-2">
            <input
              autoFocus
              aria-label="Workspace name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Workspace name"
              className={clsx('flex-1', inputClass)}
            />
            <Button variant="primary" size="sm" onClick={() => createMut.mutate()} isLoading={createMut.isPending} disabled={!name.trim()}>
              Create
            </Button>
          </div>
        )}

        <div className="mt-3 space-y-1.5">
          {wsQ.isLoading ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            wsQ.data?.map((w) => {
              const role = roleByWorkspace.get(w.id)
              const renaming = renamingId === w.id
              return (
                <div key={w.id} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                  <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                    <Building2 size={14} className="flex-shrink-0 text-slate-400" />
                    {renaming ? (
                      <input
                        autoFocus
                        aria-label="New workspace name"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && renameValue.trim()) renameMut.mutate({ id: w.id, newName: renameValue.trim() })
                          if (e.key === 'Escape') setRenamingId(null)
                        }}
                        className={clsx('max-w-56 py-1', inputClass)}
                      />
                    ) : (
                      <>
                        <span className="truncate font-medium text-slate-900 dark:text-white">{w.name}</span>
                        <span className="hidden text-xs text-slate-400 sm:inline">{w.slug}</span>
                        {role && <Badge variant={role === 'owner' ? 'brand' : 'neutral'} label={role} />}
                      </>
                    )}
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-1">
                    {renaming ? (
                      <Button size="sm" variant="primary" icon={Check} isLoading={renameMut.isPending} disabled={!renameValue.trim()} onClick={() => renameMut.mutate({ id: w.id, newName: renameValue.trim() })}>
                        Save
                      </Button>
                    ) : (
                      <>
                        {role === 'owner' && (
                          <Button size="sm" variant="ghost" icon={Pencil} onClick={() => { setRenamingId(w.id); setRenameValue(w.name) }} aria-label={`Rename ${w.name}`} />
                        )}
                        <Button size="sm" variant="ghost" onClick={() => switchMut.mutate(w.id)} isLoading={switchMut.isPending}>
                          Switch
                        </Button>
                      </>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </Card>

      <MembersCard />
    </div>
  )
}

function MembersCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const meQ = useQuery({ queryKey: ['me'], queryFn: auth.me })
  // Without decoding the JWT the best proxy for "active" is the first
  // membership; member lists are identical for any workspace the user owns
  // alone, which is the common single-tenant case here.
  const me = meQ.data?.workspaces?.[0]
  const workspaceId = me?.id
  const myRole = me?.role
  const myUserId = meQ.data?.id
  const canManage = myRole === 'owner' || myRole === 'admin'

  const membersQ = useQuery({
    queryKey: ['workspace-members', workspaceId],
    queryFn: () => workspaces.members(workspaceId!),
    enabled: Boolean(workspaceId),
  })
  const invitesQ = useQuery({
    queryKey: ['workspace-invites', workspaceId],
    queryFn: () => workspaces.invites(workspaceId!),
    enabled: Boolean(workspaceId) && canManage,
  })

  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member')

  const inviteMut = useMutation({
    mutationFn: () => workspaces.createInvite(workspaceId!, inviteEmail.trim(), inviteRole),
    onSuccess: () => {
      setInviteEmail('')
      toast.success('Invite created')
      qc.invalidateQueries({ queryKey: ['workspace-invites', workspaceId] })
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : 'Invite failed'),
  })
  const revokeMut = useMutation({
    mutationFn: (inviteId: string) => workspaces.revokeInvite(workspaceId!, inviteId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['workspace-invites', workspaceId] }),
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : 'Revoke failed'),
  })
  const removeMut = useMutation({
    mutationFn: (userId: string) => workspaces.removeMember(workspaceId!, userId),
    onSuccess: () => {
      toast.success('Member removed')
      qc.invalidateQueries({ queryKey: ['workspace-members', workspaceId] })
    },
    onError: (e: unknown) => toast.error(e instanceof Error ? e.message : 'Remove failed'),
  })

  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <UsersIcon size={14} className="text-slate-400" />
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Members</p>
      </div>

      <div className="mt-3 space-y-1.5">
        {membersQ.isLoading ? (
          <p className="text-sm text-slate-500">Loading…</p>
        ) : (membersQ.data ?? []).length === 0 ? (
          <p className="text-sm text-slate-400">No members found.</p>
        ) : (
          membersQ.data?.map((m) => {
            const isSelf = m.user_id === myUserId
            const removable = canManage && !isSelf && m.role !== 'owner'
            return (
              <div key={m.user_id} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800">
                <span className="truncate font-medium text-slate-900 dark:text-white">
                  {m.email}{isSelf && <span className="ml-1.5 text-xs text-slate-400">(you)</span>}
                </span>
                <div className="flex items-center gap-2">
                  <Badge variant={m.role === 'owner' ? 'brand' : 'neutral'} label={m.role} />
                  {removable && (
                    <button
                      type="button"
                      onClick={() => removeMut.mutate(m.user_id)}
                      disabled={removeMut.isPending}
                      className="text-xs font-medium text-red-500 hover:text-red-600 disabled:opacity-50"
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* Pending invites + invite form are owner/admin only — the API enforces
          the same, but hiding the controls avoids a guaranteed-403 click. */}
      {canManage && (
        <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-800">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Pending invites</p>
          <div className="mt-2 space-y-1.5">
            {(invitesQ.data ?? []).length === 0 ? (
              <p className="text-sm text-slate-400">No pending invites.</p>
            ) : (
              invitesQ.data?.map((inv) => (
                <div key={inv.id} className="flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-800">
                  <span className="truncate text-slate-700 dark:text-slate-200">{inv.email}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="neutral" label={inv.role} />
                    <button
                      type="button"
                      onClick={() => revokeMut.mutate(inv.id)}
                      disabled={revokeMut.isPending}
                      className="text-xs font-medium text-red-500 hover:text-red-600 disabled:opacity-50"
                    >
                      Revoke
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>

          <form
            className="mt-3 flex flex-wrap items-center gap-2"
            onSubmit={(e: FormEvent) => {
              e.preventDefault()
              if (inviteEmail.trim()) inviteMut.mutate()
            }}
          >
            <input
              type="email"
              required
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              placeholder="teammate@company.com"
              aria-label="Invite email"
              className={clsx(inputClass, 'flex-1 min-w-[12rem]')}
            />
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value as 'admin' | 'member')}
              aria-label="Invite role"
              className={clsx(inputClass, 'w-auto')}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
            <Button type="submit" size="sm" icon={Plus} isLoading={inviteMut.isPending}>
              Invite
            </Button>
          </form>
        </div>
      )}
    </Card>
  )
}

function AppearanceTab() {
  const { theme, set } = useTheme()
  const options = [
    { value: 'light' as const, label: 'Light', icon: Sun, hint: 'Bright surfaces, dark text' },
    { value: 'dark' as const, label: 'Dark', icon: Moon, hint: 'Low-light control room' },
  ]
  return (
    <Card className="p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Theme</p>
      <div className="mt-3 grid max-w-md grid-cols-2 gap-3">
        {options.map(({ value, label, icon: Icon, hint }) => {
          const active = theme === value
          return (
            <button
              key={value}
              type="button"
              onClick={() => set(value)}
              className={clsx(
                'rounded-xl border p-4 text-left transition-colors',
                active
                  ? 'border-brand-400 bg-brand-50 ring-2 ring-brand-100 dark:bg-brand-900/20 dark:ring-brand-900'
                  : 'border-slate-200 hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-600',
              )}
            >
              <div className="flex items-center justify-between">
                <Icon size={16} className={active ? 'text-brand-600 dark:text-brand-400' : 'text-slate-400'} />
                {active && <Check size={14} className="text-brand-600 dark:text-brand-400" />}
              </div>
              <p className="mt-2 text-sm font-semibold text-slate-900 dark:text-white">{label}</p>
              <p className="mt-0.5 text-xs text-slate-500">{hint}</p>
            </button>
          )
        })}
      </div>
    </Card>
  )
}

function ApiKeysCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const keysQ = useQuery({ queryKey: ['api-keys'], queryFn: apiKeys.list })

  const [name, setName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: () => apiKeys.create(name.trim()),
    onSuccess: (data) => {
      setNewKey(data.key)
      setName('')
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      toast.success('API key created — copy it now, it will not be shown again')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not create key'),
  })
  const revokeMut = useMutation({
    mutationFn: (id: string) => apiKeys.revoke(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['api-keys'] })
      toast.success('API key revoked')
    },
  })

  function copy(value: string) {
    navigator.clipboard?.writeText(value).then(
      () => toast.success('Copied'),
      () => toast.error('Copy failed'),
    )
  }

  const keys = keysQ.data ?? []
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <KeyRound size={14} className="text-slate-400" />
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">API keys</p>
      </div>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Authenticate the public API (<code>/public/v1</code>) with{' '}
        <code>Authorization: Bearer &lt;key&gt;</code>. Keys are stored hashed and shown once.
      </p>

      <div className="mt-3 flex items-center gap-2">
        <input
          aria-label="API key name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Key name (e.g. n8n production)"
          className={clsx('flex-1', inputClass)}
        />
        <Button
          variant="primary" size="sm" icon={Plus}
          onClick={() => createMut.mutate()}
          isLoading={createMut.isPending} disabled={!name.trim()}
        >
          Create
        </Button>
      </div>

      {newKey && (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-900/20">
          <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">
            Copy this key now — it will never be shown again.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-white px-2 py-1 text-xs dark:bg-slate-800">{newKey}</code>
            <Button size="sm" variant="secondary" icon={Copy} onClick={() => copy(newKey)}>
              Copy
            </Button>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {keys.length === 0 && <p className="text-xs text-slate-400">No API keys yet.</p>}
        {keys.map((k) => (
          <div key={k.id} className="flex items-center justify-between rounded-lg border border-slate-100 px-3 py-2 dark:border-slate-800">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{k.name || 'Unnamed key'}</p>
              <p className="text-xs text-slate-400">
                <code>{k.key_prefix}…</code>
                {k.last_used_at ? ` · last used ${new Date(k.last_used_at).toLocaleDateString()}` : ' · never used'}
              </p>
            </div>
            {k.revoked_at ? (
              <Badge variant="danger" label="Revoked" />
            ) : (
              <Button size="sm" variant="ghost" icon={Trash2} onClick={() => revokeMut.mutate(k.id)}>
                Revoke
              </Button>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

function WebhookSubscriptionsCard() {
  const qc = useQueryClient()
  const toast = useToast()
  const subsQ = useQuery({ queryKey: ['webhook-subs'], queryFn: webhookSubscriptions.list })

  const [url, setUrl] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [newSecret, setNewSecret] = useState<string | null>(null)

  const createMut = useMutation({
    mutationFn: () => webhookSubscriptions.create({ url: url.trim(), event_types: selected }),
    onSuccess: (data) => {
      setNewSecret(data.secret ?? null)
      setUrl('')
      setSelected([])
      qc.invalidateQueries({ queryKey: ['webhook-subs'] })
      toast.success('Webhook subscription created')
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not create subscription'),
  })
  const toggleMut = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) =>
      webhookSubscriptions.update(id, { active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhook-subs'] }),
  })
  const removeMut = useMutation({
    mutationFn: (id: string) => webhookSubscriptions.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['webhook-subs'] })
      toast.success('Subscription deleted')
    },
  })
  const testMut = useMutation({
    mutationFn: (id: string) => webhookSubscriptions.test(id),
    onSuccess: (res) =>
      res.delivered
        ? toast.success(`Ping delivered (HTTP ${res.status_code})`)
        : toast.error(`Ping failed: ${res.error ?? 'unknown'}`),
  })

  function toggleEvent(evt: string) {
    setSelected((prev) => (prev.includes(evt) ? prev.filter((e) => e !== evt) : [...prev, evt]))
  }
  function copy(value: string) {
    navigator.clipboard?.writeText(value).then(() => toast.success('Copied'))
  }

  const subs = subsQ.data ?? []
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2">
        <Webhook size={14} className="text-slate-400" />
        <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Outbound webhooks</p>
      </div>
      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
        Deliver domain events (lead replied, invite accepted, campaign completed, lead enriched,
        hot lead) to your URL. Each delivery is HMAC-signed (<code>X-Omni-Signature</code>).
      </p>

      <div className="mt-3 space-y-2">
        <input
          aria-label="Webhook URL"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-app.n8n.cloud/webhook/omni"
          className={inputClass}
        />
        <div className="flex flex-wrap gap-2">
          {WEBHOOK_EVENT_TYPES.map((evt) => (
            <button
              key={evt}
              type="button"
              onClick={() => toggleEvent(evt)}
              className={clsx(
                'rounded-full border px-3 py-1 text-xs',
                selected.includes(evt)
                  ? 'border-brand-400 bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300'
                  : 'border-slate-200 text-slate-500 dark:border-slate-700',
              )}
            >
              {evt}
            </button>
          ))}
        </div>
        <p className="text-xs text-slate-400">No events selected = deliver all supported events.</p>
        <Button
          variant="primary" size="sm" icon={Plus}
          onClick={() => createMut.mutate()}
          isLoading={createMut.isPending} disabled={!url.trim()}
        >
          Add subscription
        </Button>
      </div>

      {newSecret && (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 dark:border-amber-700 dark:bg-amber-900/20">
          <p className="text-xs font-semibold text-amber-800 dark:text-amber-300">
            Signing secret — copy it now to verify deliveries.
          </p>
          <div className="mt-2 flex items-center gap-2">
            <code className="flex-1 break-all rounded bg-white px-2 py-1 text-xs dark:bg-slate-800">{newSecret}</code>
            <Button size="sm" variant="secondary" icon={Copy} onClick={() => copy(newSecret)}>Copy</Button>
          </div>
        </div>
      )}

      <div className="mt-4 space-y-2">
        {subs.length === 0 && <p className="text-xs text-slate-400">No webhook subscriptions yet.</p>}
        {subs.map((s) => (
          <div key={s.id} className="rounded-lg border border-slate-100 px-3 py-2 dark:border-slate-800">
            <div className="flex items-center justify-between gap-2">
              <p className="min-w-0 truncate text-sm font-medium">{s.url}</p>
              <div className="flex shrink-0 items-center gap-1">
                <Badge variant={s.active ? 'success' : 'neutral'} label={s.active ? 'Active' : 'Paused'} />
                <Button size="sm" variant="ghost" icon={Send} onClick={() => testMut.mutate(s.id)}>Test</Button>
                <Button
                  size="sm" variant="ghost"
                  onClick={() => toggleMut.mutate({ id: s.id, active: !s.active })}
                >
                  {s.active ? 'Pause' : 'Resume'}
                </Button>
                <Button size="sm" variant="ghost" icon={Trash2} onClick={() => removeMut.mutate(s.id)}>Delete</Button>
              </div>
            </div>
            <p className="mt-1 text-xs text-slate-400">
              {s.event_types.length ? s.event_types.join(', ') : 'all events'}
              {s.last_status != null ? ` · last status ${s.last_status}` : ''}
            </p>
          </div>
        ))}
      </div>
    </Card>
  )
}

function DeveloperTab() {
  return (
    <div className="space-y-6">
      <ApiKeysCard />
      <WebhookSubscriptionsCard />
    </div>
  )
}

export default function Settings() {
  const [tab, setTab] = useState('account')
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Settings"
        title="Settings"
        description="Your account, workspaces, and how Omni looks."
      />
      <Tabs
        items={[
          { value: 'account', label: 'Account', icon: User },
          { value: 'workspace', label: 'Workspace', icon: Building2 },
          { value: 'developer', label: 'Developer', icon: Code2 },
          { value: 'appearance', label: 'Appearance', icon: Sun },
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'account' && <AccountTab />}
      {tab === 'workspace' && <WorkspaceTab />}
      {tab === 'developer' && <DeveloperTab />}
      {tab === 'appearance' && <AppearanceTab />}
    </div>
  )
}
