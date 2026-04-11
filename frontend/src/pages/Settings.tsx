import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { api } from '../api/client'
import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import Modal from '../components/Modal'
import { useToast } from '../components/Toast'
import { formatDate } from '../lib/time'

type SettingsTab = 'linkedin' | 'email' | 'voice'

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
      toast.success('LinkedIn account added.')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to add LinkedIn account.'),
  })

  const addEmail = useMutation({
    mutationFn: async (payload: { from_name: string; from_email: string; resend_api_key: string }) =>
      (await api.post('/accounts/email', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'email'] })
      toast.success('Email account added.')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to add email account.'),
  })

  const addVoice = useMutation({
    mutationFn: async (payload: { retell_agent_id: string; name: string }) =>
      (await api.post('/accounts/voice', payload)).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['settings', 'voice'] })
      toast.success('Voice agent added.')
      setModalOpen(false)
    },
    onError: () => toast.error('Failed to add voice agent.'),
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
      toast.success('Account removed.')
    },
    onError: () => toast.error('Failed to remove account.'),
  })

  async function handleTest(id: string) {
    setTestingId(id)
    try {
      const { data } = await api.post<{ ok: boolean; error?: string }>(`/accounts/linkedin/${id}/test`)
      setTestResults((prev) => ({ ...prev, [id]: data }))
      if (data.ok) toast.success('Connection test passed.')
      else toast.error(data.error || 'Connection test failed.')
    } catch {
      setTestResults((prev) => ({ ...prev, [id]: { ok: false, error: 'Request failed' } }))
      toast.error('Connection test failed.')
    } finally {
      setTestingId(null)
    }
  }

  const busy = addLinkedIn.isPending || addEmail.isPending || addVoice.isPending

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Settings</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">
          Account surfaces for LinkedIn, email, and voice delivery
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
          Configure sending identities and test integrations without leaving the app shell.
        </p>
      </section>

      <div className="flex flex-wrap gap-2">
        {(['linkedin', 'email', 'voice'] as SettingsTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`rounded-full px-4 py-2 text-sm font-medium transition ${
              activeTab === tab ? 'bg-sky-500 text-white' : 'bg-white text-slate-500 hover:bg-slate-100'
            }`}
          >
            {tab === 'linkedin' ? 'LinkedIn Accounts' : tab === 'email' ? 'Email Accounts' : 'Voice Agents'}
          </button>
        ))}
      </div>

      <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {activeTab === 'linkedin' ? 'LinkedIn accounts' : activeTab === 'email' ? 'Email accounts' : 'Voice agents'}
            </h2>
            <p className="text-sm text-slate-500">Provisioned sending identities and test hooks.</p>
          </div>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-600 transition-colors"
          >
            Add {activeTab === 'voice' ? 'agent' : 'account'}
          </button>
        </div>

        {activeTab === 'linkedin' && (
          <DataTable
            columns={[
              { key: 'name', header: 'Name', render: (row: LinkedInAccount) => <span className="font-medium text-slate-900">{row.name}</span> },
              { key: 'unipile_id', header: 'Unipile ID', render: (row: LinkedInAccount) => <span className="font-mono text-xs text-slate-500">{row.unipile_id}</span> },
              { key: 'daily_invite_cap', header: 'Daily cap', className: 'text-right tabular-nums' },
              { key: 'is_active', header: 'Status', render: (row: LinkedInAccount) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus /> },
              {
                key: 'actions',
                header: '',
                render: (row: LinkedInAccount) => (
                  <div className="flex items-center justify-end gap-2">
                    {testResults[row.id] && (
                      <span className={`text-xs font-medium ${testResults[row.id].ok ? 'text-emerald-600' : 'text-rose-600'}`}>
                        {testResults[row.id].ok ? 'OK' : 'Failed'}
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => void handleTest(row.id)}
                      disabled={testingId === row.id}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition-colors"
                    >
                      {testingId === row.id && <Loader2 size={12} className="animate-spin" />}
                      Test
                    </button>
                    <button
                      type="button"
                      onClick={() => void deleteAccount.mutateAsync({ type: 'linkedin', id: row.id })}
                      className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      Remove
                    </button>
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
              { key: 'from_name', header: 'From name' },
              { key: 'from_email', header: 'From email', render: (row: EmailAccount) => <span className="font-mono text-xs text-slate-600">{row.from_email}</span> },
              { key: 'is_active', header: 'Status', render: (row: EmailAccount) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus /> },
              { key: 'created_at', header: 'Created', render: (row: EmailAccount) => formatDate(row.created_at) },
              {
                key: 'remove',
                header: '',
                render: (row: EmailAccount) => (
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => void deleteAccount.mutateAsync({ type: 'email', id: row.id })}
                      className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      Remove
                    </button>
                  </div>
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
              { key: 'name', header: 'Name' },
              { key: 'retell_agent_id', header: 'Retell agent ID', render: (row: VoiceAgent) => <span className="font-mono text-xs text-slate-600">{row.retell_agent_id}</span> },
              { key: 'is_active', header: 'Status', render: (row: VoiceAgent) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus /> },
              {
                key: 'remove',
                header: '',
                render: (row: VoiceAgent) => (
                  <div className="flex justify-end">
                    <button
                      type="button"
                      onClick={() => void deleteAccount.mutateAsync({ type: 'voice', id: row.id })}
                      className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600 hover:bg-rose-50 transition-colors"
                    >
                      Remove
                    </button>
                  </div>
                ),
              },
            ]}
            rows={voiceQuery.data || []}
            loading={voiceQuery.isLoading}
            emptyMessage="No voice agents configured."
          />
        )}
      </section>

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
  onCreateEmail: (p: { from_name: string; from_email: string; resend_api_key: string }) => Promise<unknown>
  onCreateVoice: (p: { retell_agent_id: string; name: string }) => Promise<unknown>
  busy: boolean
}) {
  const [linkedin, setLinkedin] = useState({ unipile_id: '', name: '', email: '', daily_invite_cap: 20 })
  const [email, setEmail]       = useState({ from_name: '', from_email: '', resend_api_key: '' })
  const [voice, setVoice]       = useState({ retell_agent_id: '', name: '' })

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (tab === 'linkedin') await onCreateLinkedIn(linkedin)
    if (tab === 'email')    await onCreateEmail(email)
    if (tab === 'voice')    await onCreateVoice(voice)
  }

  const title =
    tab === 'linkedin' ? 'Add LinkedIn account' :
    tab === 'email'    ? 'Add email account'    :
                         'Add voice agent'

  return (
    <Modal title={title} open={open} onClose={onClose}>
      <form className="space-y-4" onSubmit={handleSubmit}>
        {tab === 'linkedin' && (
          <>
            <input className={inputCls} placeholder="Account name" value={linkedin.name} onChange={(e) => setLinkedin({ ...linkedin, name: e.target.value })} required />
            <input className={inputCls} placeholder="Unipile ID" value={linkedin.unipile_id} onChange={(e) => setLinkedin({ ...linkedin, unipile_id: e.target.value })} required />
            <input className={inputCls} placeholder="Email (optional)" value={linkedin.email} onChange={(e) => setLinkedin({ ...linkedin, email: e.target.value })} />
            <input className={inputCls} type="number" placeholder="Daily invite cap" value={linkedin.daily_invite_cap} onChange={(e) => setLinkedin({ ...linkedin, daily_invite_cap: Number(e.target.value) })} required />
          </>
        )}
        {tab === 'email' && (
          <>
            <input className={inputCls} placeholder="From name" value={email.from_name} onChange={(e) => setEmail({ ...email, from_name: e.target.value })} required />
            <input className={inputCls} placeholder="From email" value={email.from_email} onChange={(e) => setEmail({ ...email, from_email: e.target.value })} required />
            <input className={inputCls} placeholder="Resend API key" value={email.resend_api_key} onChange={(e) => setEmail({ ...email, resend_api_key: e.target.value })} required />
          </>
        )}
        {tab === 'voice' && (
          <>
            <input className={inputCls} placeholder="Agent name" value={voice.name} onChange={(e) => setVoice({ ...voice, name: e.target.value })} required />
            <input className={inputCls} placeholder="Retell agent ID" value={voice.retell_agent_id} onChange={(e) => setVoice({ ...voice, retell_agent_id: e.target.value })} required />
          </>
        )}
        <div className="flex justify-end gap-3 pt-1">
          <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">
            Cancel
          </button>
          <button type="submit" disabled={busy} className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-600 disabled:opacity-60 transition-colors">
            {busy ? 'Saving...' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

const inputCls =
  'w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100'
