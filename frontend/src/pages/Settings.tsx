import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Shield, ShieldCheck, ShieldX, Eye, EyeOff, Trash2, Plus, Slack, Mail, PowerOff, Power, Linkedin, MessageSquare, Phone, Globe, Bell, Save } from 'lucide-react'

import { api } from '../api/client'
import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import Modal from '../components/Modal'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/time'
import PageHeader from '../components/PageHeader'
import Tabs from '../components/Tabs'
import Button from '../components/Button'
import Card from '../components/Card'

type SettingsTab = 'linkedin' | 'email' | 'voice' | 'integrations' | 'notifications'

type LinkedInAccount = {
  id: string
  unipile_id: string
  name: string
  email?: string | null
  daily_invite_cap: number
  is_active: boolean
}

type EmailAccount = {
  id: string
  from_name: string
  from_email: string
  is_active: boolean
  created_at?: string
}

type VoiceAgent = {
  id: string
  retell_agent_id: string
  name: string
  is_active: boolean
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('linkedin')
  const [modalOpen, setModalOpen] = useState(false)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; error?: string }>>({})
  const [testingId, setTestingId] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const toast = useToast()

  const linkedinQuery = useQuery({
    queryKey: ['settings', 'linkedin'],
    queryFn: async () => (await api.get<LinkedInAccount[]>('/accounts/linkedin')).data,
  })
  const emailQuery = useQuery({
    queryKey: ['settings', 'email'],
    queryFn: async () => (await api.get<EmailAccount[]>('/accounts/email')).data,
  })
  const voiceQuery = useQuery({
    queryKey: ['settings', 'voice'],
    queryFn: async () => (await api.get<VoiceAgent[]>('/accounts/voice')).data,
  })

  const addLinkedIn = useMutation({
    mutationFn: async (payload: { unipile_id: string; name: string; email?: string; daily_invite_cap: number }) =>
      (await api.post('/accounts/linkedin', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'linkedin'] })
      toast.success('LinkedIn account added')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to add LinkedIn account'),
  })

  const addEmail = useMutation({
    mutationFn: async (payload: { from_name: string; from_email: string; smtp_host: string; smtp_port: number; smtp_username: string; smtp_password: string; smtp_use_tls: boolean }) =>
      (await api.post('/accounts/email', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'email'] })
      toast.success('Email account added')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to add email account'),
  })

  const addVoice = useMutation({
    mutationFn: async (payload: { retell_agent_id: string; name: string }) =>
      (await api.post('/accounts/voice', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'voice'] })
      toast.success('Voice agent added')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to add voice agent'),
  })

  const deleteAccount = useMutation({
    mutationFn: async ({ type, id }: { type: SettingsTab; id: string }) => {
      const path =
        type === 'linkedin' ? `/accounts/linkedin/${id}` :
        type === 'email'    ? `/accounts/email/${id}`    :
                              `/accounts/voice/${id}`
      await api.delete(path)
    },
    onSuccess: (_, vars) => {
      void queryClient.invalidateQueries({ queryKey: ['settings', vars.type] })
      toast.success('Account removed')
    },
    onError: () => toast.error('Failed to remove account'),
  })

  async function handleTest(id: string) {
    setTestingId(id)
    try {
      const { data } = await api.post<{ ok: boolean; error?: string }>(`/accounts/linkedin/${id}/test`)
      setTestResults((prev) => ({ ...prev, [id]: data }))
      if (data.ok) toast.success('Connection test passed')
      else toast.error(data.error || 'Connection test failed')
    } catch {
      setTestResults((prev) => ({ ...prev, [id]: { ok: false, error: 'Request failed' } }))
      toast.error('Connection test failed')
    } finally {
      setTestingId(null)
    }
  }

  const busy = addLinkedIn.isPending || addEmail.isPending || addVoice.isPending

  return (
    <div className="space-y-8 pb-12">
      <PageHeader
        screenLabel="Settings"
        eyebrow="System"
        title="Settings"
        description="Provisioned sending identities, encrypted API keys, and notification channels."
        actions={
          (activeTab === 'linkedin' || activeTab === 'email' || activeTab === 'voice') && (
            <Button
              variant="primary"
              size="md"
              icon={Plus}
              onClick={() => setModalOpen(true)}
            >
              Add {activeTab === 'voice' ? 'Agent' : 'Account'}
            </Button>
          )
        }
      />

      <Tabs
        activeTab={activeTab}
        onChange={(id) => setActiveTab(id as SettingsTab)}
        tabs={[
          { id: 'linkedin', label: 'LinkedIn', icon: Linkedin },
          { id: 'email', label: 'Email', icon: Mail },
          { id: 'voice', label: 'Voice', icon: Phone },
          { id: 'integrations', label: 'Integrations', icon: Globe },
          { id: 'notifications', label: 'Notifications', icon: Bell },
        ]}
      />

      <Card padding="none">
        {activeTab === 'linkedin' && (
          <DataTable
            columns={[
              { key: 'name', header: 'Name', render: (row: LinkedInAccount) => <span className="font-bold text-slate-900 dark:text-white">{row.name}</span> },
              { key: 'unipile_id', header: 'Unipile ID', render: (row: LinkedInAccount) => <span className="font-mono text-[11px] text-slate-400">{row.unipile_id}</span> },
              { key: 'daily_invite_cap', header: 'Daily Cap', className: 'text-right tabular-nums font-semibold' },
              { key: 'is_active', header: 'Status', render: (row: LinkedInAccount) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus dot /> },
              {
                key: 'actions',
                header: '',
                align: 'right',
                render: (row: LinkedInAccount) => (
                  <div className="flex items-center justify-end gap-3">
                    {testResults[row.id] && (
                      <Badge 
                        label={testResults[row.id].ok ? 'Verified' : 'Error'} 
                        variant={testResults[row.id].ok ? 'success' : 'danger'} 
                        size="xs" 
                      />
                    )}
                    <Button
                      variant="secondary"
                      size="xs"
                      isLoading={testingId === row.id}
                      onClick={() => void handleTest(row.id)}
                    >
                      Test
                    </Button>
                    <Button
                      variant="danger"
                      size="xs"
                      icon={Trash2}
                      onClick={() => { if (confirm('Remove this account?')) deleteAccount.mutate({ type: 'linkedin', id: row.id }) }}
                    />
                  </div>
                ),
              },
            ]}
            rows={linkedinQuery.data || []}
            loading={linkedinQuery.isLoading}
            emptyMessage="No LinkedIn accounts configured."
          />
        )}

        {activeTab === 'email' && (
          <DataTable
            columns={[
              { key: 'from_name', header: 'From Name', render: (row: EmailAccount) => <span className="font-bold text-slate-900 dark:text-white">{row.from_name}</span> },
              { key: 'from_email', header: 'From Email', render: (row: EmailAccount) => <span className="font-mono text-[11px] text-slate-400">{row.from_email}</span> },
              { key: 'is_active', header: 'Status', render: (row: EmailAccount) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus dot /> },
              { key: 'created_at', header: 'Created', render: (row: EmailAccount) => <span className="text-xs text-slate-500 tabular-nums">{formatDate(row.created_at)}</span> },
              {
                key: 'remove',
                header: '',
                align: 'right',
                render: (row: EmailAccount) => (
                  <Button
                    variant="danger"
                    size="xs"
                    icon={Trash2}
                    onClick={() => { if (confirm('Remove this account?')) deleteAccount.mutate({ type: 'email', id: row.id }) }}
                  />
                ),
              },
            ]}
            rows={emailQuery.data || []}
            loading={emailQuery.isLoading}
            emptyMessage="No email accounts configured."
          />
        )}

        {activeTab === 'voice' && (
          <DataTable
            columns={[
              { key: 'name', header: 'Name', render: (row: VoiceAgent) => <span className="font-bold text-slate-900 dark:text-white">{row.name}</span> },
              { key: 'retell_agent_id', header: 'Retell Agent ID', render: (row: VoiceAgent) => <span className="font-mono text-[11px] text-slate-400">{row.retell_agent_id}</span> },
              { key: 'is_active', header: 'Status', render: (row: VoiceAgent) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus dot /> },
              {
                key: 'remove',
                header: '',
                align: 'right',
                render: (row: VoiceAgent) => (
                  <Button
                    variant="danger"
                    size="xs"
                    icon={Trash2}
                    onClick={() => { if (confirm('Remove this agent?')) deleteAccount.mutate({ type: 'voice', id: row.id }) }}
                  />
                ),
              },
            ]}
            rows={voiceQuery.data || []}
            loading={voiceQuery.isLoading}
            emptyMessage="No voice agents configured."
          />
        )}

        {activeTab === 'integrations' && <div className="p-6"><IntegrationsPanel /></div>}
        {activeTab === 'notifications' && <div className="p-6"><NotificationChannelsPanel /></div>}
      </Card>

      <AccountModal
        open={modalOpen}
        tab={activeTab}
        onClose={() => setModalOpen(false)}
        onCreateLinkedIn={(p) => addLinkedIn.mutateAsync(p)}
        onCreateEmail={(p) => addEmail.mutateAsync(p)}
        onCreateVoice={(p) => addVoice.mutateAsync(p)}
        busy={busy}
      />
    </div>
  )
}

function AccountModal({
  open, tab, onClose,
  onCreateLinkedIn, onCreateEmail, onCreateVoice, busy,
}: {
  open: boolean
  tab: SettingsTab
  onClose: () => void
  onCreateLinkedIn: (p: { unipile_id: string; name: string; email?: string; daily_invite_cap: number }) => Promise<unknown>
  onCreateEmail: (p: { from_name: string; from_email: string; smtp_host: string; smtp_port: number; smtp_username: string; smtp_password: string; smtp_use_tls: boolean }) => Promise<unknown>
  onCreateVoice: (p: { retell_agent_id: string; name: string }) => Promise<unknown>
  busy: boolean
}) {
  const [linkedin, setLinkedin] = useState({ unipile_id: '', name: '', email: '', daily_invite_cap: 20 })
  const [email, setEmail]       = useState({ from_name: '', from_email: '', smtp_host: '', smtp_port: 587, smtp_username: '', smtp_password: '', smtp_use_tls: true })
  const [voice, setVoice]       = useState({ retell_agent_id: '', name: '' })

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (tab === 'linkedin') await onCreateLinkedIn(linkedin)
    if (tab === 'email')    await onCreateEmail(email)
    if (tab === 'voice')    await onCreateVoice(voice)
  }

  const title =
    tab === 'linkedin' ? 'Add LinkedIn Account' :
    tab === 'email'    ? 'Add Email Account'    :
                         'Add Voice Agent'

  return (
    <Modal title={title} open={open} onClose={onClose}>
      <form className="space-y-5" onSubmit={handleSubmit}>
        {tab === 'linkedin' && (
          <div className="space-y-4">
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Account Name</label>
              <input className={inputCls} placeholder="e.g. Personal Profile" value={linkedin.name} onChange={(e) => setLinkedin({ ...linkedin, name: e.target.value })} required />
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Unipile ID</label>
              <input className={inputCls} placeholder="unipile_..." value={linkedin.unipile_id} onChange={(e) => setLinkedin({ ...linkedin, unipile_id: e.target.value })} required />
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Email (Optional)</label>
              <input className={inputCls} placeholder="email@example.com" value={linkedin.email} onChange={(e) => setLinkedin({ ...linkedin, email: e.target.value })} />
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Daily Invite Cap</label>
              <input className={inputCls} type="number" value={linkedin.daily_invite_cap} onChange={(e) => setLinkedin({ ...linkedin, daily_invite_cap: Number(e.target.value) })} required />
            </div>
          </div>
        )}
        {tab === 'email' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">From Name</label>
                <input className={inputCls} placeholder="John Doe" value={email.from_name} onChange={(e) => setEmail({ ...email, from_name: e.target.value })} required />
              </div>
              <div>
                <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">From Email</label>
                <input className={inputCls} placeholder="john@example.com" value={email.from_email} onChange={(e) => setEmail({ ...email, from_email: e.target.value })} required />
              </div>
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">SMTP Host</label>
              <input className={inputCls} placeholder="smtp.gmail.com" value={email.smtp_host} onChange={(e) => setEmail({ ...email, smtp_host: e.target.value })} required />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Port</label>
                <input className={inputCls} type="number" placeholder="587" value={email.smtp_port} onChange={(e) => setEmail({ ...email, smtp_port: Number(e.target.value) })} required />
              </div>
              <div className="flex items-end">
                <label className="flex h-[44px] w-full items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 text-xs font-bold text-slate-700 cursor-pointer transition-colors hover:border-brand-300 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300">
                  <input type="checkbox" className="rounded text-brand-600 focus:ring-brand-500" checked={email.smtp_use_tls} onChange={(e) => setEmail({ ...email, smtp_use_tls: e.target.checked })} />
                  Use STARTTLS
                </label>
              </div>
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">SMTP Username</label>
              <input className={inputCls} placeholder="user@example.com" value={email.smtp_username} onChange={(e) => setEmail({ ...email, smtp_username: e.target.value })} required />
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">SMTP Password</label>
              <input className={inputCls} type="password" placeholder="App password..." value={email.smtp_password} onChange={(e) => setEmail({ ...email, smtp_password: e.target.value })} required />
            </div>
          </div>
        )}
        {tab === 'voice' && (
          <div className="space-y-4">
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Agent Name</label>
              <input className={inputCls} placeholder="e.g. AI Assistant" value={voice.name} onChange={(e) => setVoice({ ...voice, name: e.target.value })} required />
            </div>
            <div>
              <label className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400">Retell Agent ID</label>
              <input className={inputCls} placeholder="agent_..." value={voice.retell_agent_id} onChange={(e) => setVoice({ ...voice, retell_agent_id: e.target.value })} required />
            </div>
          </div>
        )}
        <div className="flex justify-end gap-3 pt-4 border-t border-slate-100 dark:border-slate-800">
          <Button variant="secondary" size="md" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" variant="primary" size="md" isLoading={busy}>Save Account</Button>
        </div>
      </form>
    </Modal>
  )
}

const inputCls =
  'w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 outline-none transition focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:focus:ring-brand-900/20'

// ── Integrations Panel ────────────────────────────────────────────────

interface ProviderConfig {
  label: string
  fields: string[]
  required: string[]
}

interface IntegrationKey {
  id: string
  provider: string
  field_name: string
  masked_value: string
  is_verified: boolean
  updated_at: string | null
}

function IntegrationsPanel() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [editProvider, setEditProvider] = useState<string | null>(null)
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({})
  const [showValues, setShowValues] = useState<Record<string, boolean>>({})
  const [verifying, setVerifying] = useState<string | null>(null)

  const providersQuery = useQuery<Record<string, ProviderConfig>>({
    queryKey: ['settings', 'integrations', 'providers'],
    queryFn: async () => (await api.get('/settings/integrations/providers')).data,
  })

  const keysQuery = useQuery<IntegrationKey[]>({
    queryKey: ['settings', 'integrations', 'keys'],
    queryFn: async () => (await api.get('/settings/integrations')).data,
  })

  const upsertKey = useMutation({
    mutationFn: async (payload: { provider: string; field_name: string; value: string }) =>
      (await api.put('/settings/integrations', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'integrations', 'keys'] })
      toast.success('Key saved and encrypted')
    },
    onError: () => toast.error('Failed to save key'),
  })

  const deleteKey = useMutation({
    mutationFn: async (payload: { provider: string; field_name: string }) =>
      (await api.delete('/settings/integrations', { data: payload })).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'integrations', 'keys'] })
      toast.success('Key removed')
    },
    onError: () => toast.error('Failed to remove key'),
  })

  async function handleVerify(provider: string) {
    setVerifying(provider)
    try {
      const { data } = await api.post<{ verified: boolean; detail: string }>(`/settings/integrations/${provider}/verify`)
      void queryClient.invalidateQueries({ queryKey: ['settings', 'integrations', 'keys'] })
      if (data.verified) toast.success(`${provider} verified!`)
      else toast.error(`${provider} failed: ${data.detail}`)
    } catch {
      toast.error('Verification request failed')
    } finally {
      setVerifying(null)
    }
  }

  function handleSaveField(provider: string, fieldName: string) {
    const val = fieldValues[`${provider}.${fieldName}`]
    if (!val?.trim()) return
    void upsertKey.mutateAsync({ provider, field_name: fieldName, value: val.trim() })
    setFieldValues((prev) => ({ ...prev, [`${provider}.${fieldName}`]: '' }))
    setEditProvider(null)
  }

  const providers = providersQuery.data || {}
  const keys = keysQuery.data || []

  function getKeyForField(provider: string, fieldName: string): IntegrationKey | undefined {
    return keys.find((k) => k.provider === provider && k.field_name === fieldName)
  }

  function isProviderVerified(provider: string): boolean | null {
    const providerKeys = keys.filter((k) => k.provider === provider)
    if (providerKeys.length === 0) return null
    return providerKeys.every((k) => k.is_verified)
  }

  if (providersQuery.isLoading) return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-slate-500">
          API keys are encrypted at rest (AES-256). Only masked previews are shown for security.
        </p>
      </div>

      <div className="grid gap-6 sm:grid-cols-2">
        {Object.entries(providers).map(([providerKey, config]) => {
          const verified = isProviderVerified(providerKey)
          const isEditing = editProvider === providerKey
          const hasAllKeys = config.required.every((f) => getKeyForField(providerKey, f))

          return (
            <div
              key={providerKey}
              className="rounded-2xl border border-slate-200 bg-slate-50/50 p-6 transition-all hover:border-brand-200 dark:border-slate-800 dark:bg-slate-900/50"
            >
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">{config.label}</h3>
                  <div className="mt-1 flex items-center gap-1.5">
                    {verified === true ? (
                      <span className="flex items-center gap-1 text-[10px] font-bold uppercase text-emerald-600">
                        <ShieldCheck size={12} /> Connected
                      </span>
                    ) : verified === false ? (
                      <span className="flex items-center gap-1 text-[10px] font-bold uppercase text-rose-500">
                        <ShieldX size={12} /> Verification Failed
                      </span>
                    ) : (
                      <span className="flex items-center gap-1 text-[10px] font-bold uppercase text-slate-400">
                        <Shield size={12} /> Not Configured
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="space-y-4">
                {config.fields.map((fieldName) => {
                  const existing = getKeyForField(providerKey, fieldName)
                  const fKey = `${providerKey}.${fieldName}`
                  const isVisible = showValues[fKey]

                  return (
                    <div key={fieldName}>
                      <label className="block text-[11px] font-bold uppercase tracking-widest text-slate-400 mb-2">
                        {fieldName.replace(/_/g, ' ')}
                        {config.required.includes(fieldName) && <span className="text-rose-500 ml-1">*</span>}
                      </label>
                      {existing && !isEditing ? (
                        <div className="flex items-center gap-2">
                          <div className="flex-1 rounded-xl bg-white border border-slate-200 px-4 py-2 font-mono text-xs text-slate-600 dark:bg-slate-900 dark:border-slate-800 dark:text-slate-400 truncate">
                            {existing.masked_value}
                          </div>
                          <button
                            type="button"
                            onClick={() => void deleteKey.mutateAsync({ provider: providerKey, field_name: fieldName })}
                            className="p-2 text-slate-300 transition-colors hover:text-rose-500 dark:hover:text-rose-400"
                            title="Remove"
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      ) : (
                        <div className="flex gap-2">
                          <input
                            type="password"
                            className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-900 outline-none transition focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:bg-slate-900 dark:border-slate-800 dark:text-white dark:focus:ring-brand-900/20"
                            placeholder={`Enter ${fieldName.replace(/_/g, ' ')}`}
                            value={fieldValues[fKey] || ''}
                            onChange={(e) => setFieldValues((p) => ({ ...p, [fKey]: e.target.value }))}
                            onKeyDown={(e) => { if (e.key === 'Enter') handleSaveField(providerKey, fieldName) }}
                          />
                          <Button
                            variant="primary"
                            size="sm"
                            disabled={!fieldValues[fKey]?.trim() || upsertKey.isPending}
                            onClick={() => handleSaveField(providerKey, fieldName)}
                          >
                            Save
                          </Button>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="mt-8 flex gap-3 pt-6 border-t border-slate-100 dark:border-slate-800">
                {!isEditing && hasAllKeys && (
                  <Button variant="secondary" size="xs" onClick={() => setEditProvider(providerKey)}>Update Keys</Button>
                )}
                {isEditing && (
                  <Button variant="secondary" size="xs" onClick={() => setEditProvider(null)}>Cancel</Button>
                )}
                {hasAllKeys && (
                  <Button
                    variant="secondary"
                    size="xs"
                    isLoading={verifying === providerKey}
                    onClick={() => void handleVerify(providerKey)}
                  >
                    Verify Connection
                  </Button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Notification channels ───────────────────────────────────────────────────

type NotificationChannel = {
  id: string
  channel_type: 'slack' | 'email'
  name: string
  config: Record<string, unknown>
  is_active: boolean
  created_at: string
}

function NotificationChannelsPanel() {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [draft, setDraft] = useState<{ channel_type: 'slack' | 'email'; name: string; target: string } | null>(null)

  const channelsQuery = useQuery<NotificationChannel[]>({
    queryKey: ['settings', 'notification-channels'],
    queryFn: async () => (await api.get('/settings/notification-channels')).data,
  })

  const createChannel = useMutation({
    mutationFn: async (payload: { channel_type: 'slack' | 'email'; name: string; config: Record<string, unknown> }) =>
      (await api.post('/settings/notification-channels', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'notification-channels'] })
      toast.success('Notification channel added')
      setDraft(null)
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to add channel'
      toast.error(msg)
    },
  })

  const toggleChannel = useMutation({
    mutationFn: async (payload: { id: string; is_active: boolean }) =>
      (await api.patch(`/settings/notification-channels/${payload.id}`, { is_active: payload.is_active })).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'notification-channels'] })
    },
    onError: () => toast.error('Failed to toggle channel'),
  })

  const deleteChannel = useMutation({
    mutationFn: async (id: string) => (await api.delete(`/settings/notification-channels/${id}`)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'notification-channels'] })
      toast.success('Channel removed')
    },
    onError: () => toast.error('Failed to remove channel'),
  })

  function handleCreate() {
    if (!draft) return
    const target = draft.target.trim()
    if (!draft.name.trim() || !target) {
      toast.error(draft.channel_type === 'slack' ? 'Name and webhook URL are required' : 'Name and destination email are required')
      return
    }
    const config = draft.channel_type === 'slack' ? { webhook_url: target } : { to: target }
    void createChannel.mutateAsync({ channel_type: draft.channel_type, name: draft.name.trim(), config })
  }

  if (channelsQuery.isLoading) {
    return <div className="flex justify-center py-12"><Loader2 className="h-8 w-8 animate-spin text-brand-500" /></div>
  }

  const channels = channelsQuery.data ?? []

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-6">
        <p className="text-sm font-medium text-slate-500 leading-relaxed max-w-xl">
          Fanned out alerts for hot-lead alerts, approvals, and delivery failures.
        </p>
        {!draft && (
          <Button variant="primary" size="sm" icon={Plus} onClick={() => setDraft({ channel_type: 'slack', name: '', target: '' })}>
            Add Channel
          </Button>
        )}
      </div>

      {draft && (
        <div className="rounded-2xl border border-brand-100 bg-brand-50/30 p-6 space-y-6 dark:border-brand-900/20 dark:bg-brand-900/10">
          <div className="flex flex-wrap gap-2">
            {(['slack', 'email'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setDraft((d) => (d ? { ...d, channel_type: t, target: '' } : d))}
                className={`inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-bold uppercase tracking-wider transition ${
                  draft.channel_type === t 
                    ? 'bg-brand-500 text-white shadow-lg shadow-brand-100 dark:shadow-none' 
                    : 'bg-white text-slate-500 border border-slate-200 hover:bg-slate-50 dark:bg-slate-900 dark:border-slate-800'
                }`}
              >
                {t === 'slack' ? <Slack size={13} /> : <Mail size={13} />}
                {t === 'slack' ? 'Slack Webhook' : 'Email Alert'}
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <label className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Display Name</label>
              <input
                type="text"
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-semibold text-slate-900 outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:bg-slate-900 dark:border-slate-800 dark:text-white dark:focus:ring-brand-900/20"
                placeholder="e.g. Sales Alerts"
                value={draft.name}
                onChange={(e) => setDraft((d) => (d ? { ...d, name: e.target.value } : d))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-[11px] font-bold uppercase tracking-widest text-slate-400">Target Destination</label>
              <input
                type={draft.channel_type === 'email' ? 'email' : 'url'}
                className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-mono text-slate-900 outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:bg-slate-900 dark:border-slate-800 dark:text-white dark:focus:ring-brand-900/20"
                placeholder={draft.channel_type === 'slack' ? 'https://hooks.slack.com/...' : 'alerts@company.com'}
                value={draft.target}
                onChange={(e) => setDraft((d) => (d ? { ...d, target: e.target.value } : d))}
                onKeyDown={(e) => { if (e.key === 'Enter') handleCreate() }}
              />
            </div>
          </div>
          <div className="flex justify-end gap-3 pt-2">
            <Button variant="secondary" size="sm" onClick={() => setDraft(null)}>Cancel</Button>
            <Button variant="primary" size="sm" isLoading={createChannel.isPending} onClick={handleCreate}>Create Channel</Button>
          </div>
        </div>
      )}

      {channels.length === 0 && !draft ? (
        <div className="rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50 p-12 text-center dark:border-slate-800">
          <p className="text-sm font-medium text-slate-400">No notification channels configured yet. Alerts will not be sent.</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {channels.map((ch) => {
            const config = (ch.config ?? {}) as { webhook_url?: string; to?: string }
            const target = ch.channel_type === 'slack' ? config.webhook_url : config.to
            return (
              <div key={ch.id} className="flex items-center gap-4 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${
                  ch.channel_type === 'slack' ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30' : 'bg-brand-50 text-brand-600 dark:bg-brand-900/30'
                }`}>
                  {ch.channel_type === 'slack' ? <Slack size={18} /> : <Mail size={18} />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-slate-900 dark:text-white truncate">{ch.name}</span>
                    <Badge label={ch.is_active ? 'active' : 'paused'} asStatus size="xs" dot />
                  </div>
                  <p className="mt-1 truncate font-mono text-[11px] text-slate-400">{target || '—'}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="secondary"
                    size="xs"
                    icon={ch.is_active ? PowerOff : Power}
                    onClick={() => toggleChannel.mutate({ id: ch.id, is_active: !ch.is_active })}
                  >
                    {ch.is_active ? 'Pause' : 'Resume'}
                  </Button>
                  <Button
                    variant="danger"
                    size="xs"
                    icon={Trash2}
                    onClick={() => { if (confirm(`Remove "${ch.name}"?`)) deleteChannel.mutate(ch.id) }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
