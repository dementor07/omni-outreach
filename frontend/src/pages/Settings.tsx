import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import Badge from '../components/Badge'
import DataTable from '../components/DataTable'
import Modal from '../components/Modal'

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

function formatDate(iso?: string | null) {
  return iso ? new Date(iso).toLocaleDateString() : '—'
}

export default function Settings() {
  const [activeTab, setActiveTab] = useState<SettingsTab>('linkedin')
  const [modalOpen, setModalOpen] = useState(false)
  const queryClient = useQueryClient()

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
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['settings', 'linkedin'] }),
  })
  const addEmail = useMutation({
    mutationFn: async (payload: { from_name: string; from_email: string; resend_api_key: string }) =>
      (await api.post('/accounts/email', payload)).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['settings', 'email'] }),
  })
  const addVoice = useMutation({
    mutationFn: async (payload: { retell_agent_id: string; name: string }) =>
      (await api.post('/accounts/voice', payload)).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['settings', 'voice'] }),
  })
  const deleteAccount = useMutation({
    mutationFn: async ({ type, id }: { type: SettingsTab; id: string }) => {
      const path =
        type === 'linkedin' ? `/accounts/linkedin/${id}` :
        type === 'email' ? `/accounts/email/${id}` :
        `/accounts/voice/${id}`
      await api.delete(path)
    },
    onSuccess: (_, variables) => void queryClient.invalidateQueries({ queryKey: ['settings', variables.type] }),
  })
  const testLinkedIn = useMutation({
    mutationFn: async (id: string) => (await api.post<{ ok: boolean; error?: string }>(`/accounts/linkedin/${id}/test`)).data,
  })

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-500">Settings</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-slate-900">Account surfaces for LinkedIn, email, and voice delivery</h1>
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
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {activeTab === 'linkedin' ? 'LinkedIn accounts' : activeTab === 'email' ? 'Email accounts' : 'Voice agents'}
            </h2>
            <p className="text-sm text-slate-500">Provisioned sending identities and test hooks.</p>
          </div>
          <button type="button" onClick={() => setModalOpen(true)} className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white">
            Add {activeTab === 'voice' ? 'agent' : 'account'}
          </button>
        </div>

        {activeTab === 'linkedin' && (
          <DataTable
            columns={[
              { key: 'name', header: 'Name' },
              { key: 'unipile_id', header: 'Unipile ID' },
              { key: 'daily_invite_cap', header: 'Daily cap', className: 'text-right' },
              { key: 'is_active', header: 'Status', render: (row: LinkedInAccount) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus /> },
              {
                key: 'test',
                header: '',
                render: (row: LinkedInAccount) => (
                  <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => void testLinkedIn.mutateAsync(row.id)} className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700">
                      Test
                    </button>
                    <button type="button" onClick={() => void deleteAccount.mutateAsync({ type: 'linkedin', id: row.id })} className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600">
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
              { key: 'from_email', header: 'From email' },
              { key: 'is_active', header: 'Status', render: (row: EmailAccount) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus /> },
              { key: 'created_at', header: 'Created', render: (row: EmailAccount) => formatDate(row.created_at) },
              {
                key: 'remove',
                header: '',
                render: (row: EmailAccount) => (
                  <div className="flex justify-end">
                    <button type="button" onClick={() => void deleteAccount.mutateAsync({ type: 'email', id: row.id })} className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600">
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
              { key: 'retell_agent_id', header: 'Retell agent ID' },
              { key: 'is_active', header: 'Status', render: (row: VoiceAgent) => <Badge label={row.is_active ? 'active' : 'paused'} asStatus /> },
              {
                key: 'remove',
                header: '',
                render: (row: VoiceAgent) => (
                  <div className="flex justify-end">
                    <button type="button" onClick={() => void deleteAccount.mutateAsync({ type: 'voice', id: row.id })} className="rounded-lg border border-rose-200 px-3 py-1.5 text-xs font-medium text-rose-600">
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

        {activeTab === 'linkedin' && testLinkedIn.data && (
          <div className={`mt-4 rounded-xl px-4 py-3 text-sm ${testLinkedIn.data.ok ? 'border border-emerald-200 bg-emerald-50 text-emerald-700' : 'border border-rose-200 bg-rose-50 text-rose-700'}`}>
            {testLinkedIn.data.ok ? 'LinkedIn account test passed.' : testLinkedIn.data.error || 'LinkedIn account test failed.'}
          </div>
        )}
      </section>

      <AccountModal
        open={modalOpen}
        tab={activeTab}
        onClose={() => setModalOpen(false)}
        onCreateLinkedIn={(payload) => addLinkedIn.mutateAsync(payload).then(() => setModalOpen(false))}
        onCreateEmail={(payload) => addEmail.mutateAsync(payload).then(() => setModalOpen(false))}
        onCreateVoice={(payload) => addVoice.mutateAsync(payload).then(() => setModalOpen(false))}
        busy={addLinkedIn.isPending || addEmail.isPending || addVoice.isPending}
      />
    </div>
  )
}

function AccountModal({
  open,
  tab,
  onClose,
  onCreateLinkedIn,
  onCreateEmail,
  onCreateVoice,
  busy,
}: {
  open: boolean
  tab: SettingsTab
  onClose: () => void
  onCreateLinkedIn: (payload: { unipile_id: string; name: string; email?: string; daily_invite_cap: number }) => Promise<unknown>
  onCreateEmail: (payload: { from_name: string; from_email: string; resend_api_key: string }) => Promise<unknown>
  onCreateVoice: (payload: { retell_agent_id: string; name: string }) => Promise<unknown>
  busy: boolean
}) {
  const [linkedin, setLinkedin] = useState({ unipile_id: '', name: '', email: '', daily_invite_cap: 20 })
  const [email, setEmail] = useState({ from_name: '', from_email: '', resend_api_key: '' })
  const [voice, setVoice] = useState({ retell_agent_id: '', name: '' })

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (tab === 'linkedin') await onCreateLinkedIn(linkedin)
    if (tab === 'email') await onCreateEmail(email)
    if (tab === 'voice') await onCreateVoice(voice)
  }

  return (
    <Modal
      title={tab === 'linkedin' ? 'Add LinkedIn account' : tab === 'email' ? 'Add email account' : 'Add voice agent'}
      open={open}
      onClose={onClose}
    >
      <form className="space-y-4" onSubmit={handleSubmit}>
        {tab === 'linkedin' && (
          <>
            <input className={inputClassName} placeholder="Account name" value={linkedin.name} onChange={(event) => setLinkedin({ ...linkedin, name: event.target.value })} required />
            <input className={inputClassName} placeholder="Unipile ID" value={linkedin.unipile_id} onChange={(event) => setLinkedin({ ...linkedin, unipile_id: event.target.value })} required />
            <input className={inputClassName} placeholder="Email (optional)" value={linkedin.email} onChange={(event) => setLinkedin({ ...linkedin, email: event.target.value })} />
            <input className={inputClassName} type="number" placeholder="Daily invite cap" value={linkedin.daily_invite_cap} onChange={(event) => setLinkedin({ ...linkedin, daily_invite_cap: Number(event.target.value) })} required />
          </>
        )}
        {tab === 'email' && (
          <>
            <input className={inputClassName} placeholder="From name" value={email.from_name} onChange={(event) => setEmail({ ...email, from_name: event.target.value })} required />
            <input className={inputClassName} placeholder="From email" value={email.from_email} onChange={(event) => setEmail({ ...email, from_email: event.target.value })} required />
            <input className={inputClassName} placeholder="Resend API key" value={email.resend_api_key} onChange={(event) => setEmail({ ...email, resend_api_key: event.target.value })} required />
          </>
        )}
        {tab === 'voice' && (
          <>
            <input className={inputClassName} placeholder="Agent name" value={voice.name} onChange={(event) => setVoice({ ...voice, name: event.target.value })} required />
            <input className={inputClassName} placeholder="Retell agent ID" value={voice.retell_agent_id} onChange={(event) => setVoice({ ...voice, retell_agent_id: event.target.value })} required />
          </>
        )}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={onClose} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600">
            Cancel
          </button>
          <button type="submit" className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white" disabled={busy}>
            {busy ? 'Saving...' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

const inputClassName =
  'w-full rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-sky-400 focus:ring-4 focus:ring-sky-100'
