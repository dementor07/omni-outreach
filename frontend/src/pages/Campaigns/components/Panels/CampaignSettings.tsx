import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Save, ExternalLink } from 'lucide-react'
import { api } from '../../../../api/client'
import { useToast } from '../../../../components/Toast'
import { CampaignPayload, useGetCampaign, useUpdateCampaign } from '../../../../hooks/useCampaigns'
import { LinkedInAccount } from '../../types'
import { labelCls, inputClassName } from '../Sidebar/Common'
import Button from '../../../../components/Button'
import Badge from '../../../../components/Badge'
import Card from '../../../../components/Card'

export function CampaignSettings({ campaignId }: { campaignId: string }) {
  const toast = useToast()
  const campaignQuery = useGetCampaign(campaignId)
  const updateCampaign = useUpdateCampaign()
  const queryClient = useQueryClient()

  const [form, setForm] = useState<Partial<CampaignPayload>>({})
  const [dirty, setDirty] = useState(false)

  const linkedinAccountsQuery = useQuery({
    queryKey: ['settings', 'linkedin'],
    queryFn: async () => (await api.get<LinkedInAccount[]>('/accounts/linkedin')).data,
  })
  const assignedQuery = useQuery({
    queryKey: ['campaign-accounts', campaignId],
    queryFn: async () => (await api.get<LinkedInAccount[]>(`/campaigns/${campaignId}/accounts`)).data,
  })

  useEffect(() => {
    if (campaignQuery.data && !dirty) {
      const c = campaignQuery.data
      setForm({
        name: c.name,
        timezone: c.timezone,
        daily_lead_cap: c.daily_lead_cap,
        invite_daily_cap: c.invite_daily_cap,
        active_hours_start: c.active_hours_start,
        active_hours_end: c.active_hours_end,
        simulation_mode: c.simulation_mode,
        screening_prompt: c.screening_prompt ?? '',
        sequence_mode: c.sequence_mode,
      })
    }
  }, [campaignQuery.data, dirty])

  const assignedIds = new Set((assignedQuery.data ?? []).map(a => a.id))

  const toggleAccount = async (accountId: string) => {
    if (assignedIds.has(accountId)) {
      await api.delete(`/campaigns/${campaignId}/accounts/${accountId}`)
    } else {
      await api.post(`/campaigns/${campaignId}/accounts`, { account_id: accountId })
    }
    void queryClient.invalidateQueries({ queryKey: ['campaign-accounts', campaignId] })
  }

  if (campaignQuery.isLoading) {
    return (
      <div className="space-y-6">
        {[0, 1, 2].map(i => <div key={i} className="h-12 skeleton rounded-xl" />)}
      </div>
    )
  }

  const update = (key: string, val: any) => {
    setForm(prev => ({ ...prev, [key]: val }))
    setDirty(true)
  }

  return (
    <div className="space-y-12 max-w-2xl">
      <form onSubmit={async (e) => { e.preventDefault(); await updateCampaign.mutateAsync({ id: campaignId, payload: form as CampaignPayload }); setDirty(false); toast.success('Settings saved'); }} className="space-y-8">
        <div>
          <label className={labelCls}>Campaign Name</label>
          <input value={form.name || ''} onChange={(e) => update('name', e.target.value)} className={inputClassName} required />
        </div>

        <div className="grid grid-cols-2 gap-8">
          <div>
            <label className={labelCls}>Daily Lead Cap</label>
            <input type="number" value={form.daily_lead_cap || 0} onChange={(e) => update('daily_lead_cap', parseInt(e.target.value) || 0)} className={inputClassName} />
            <p className="mt-2 text-[11px] text-slate-400 font-medium">Hard limit at intake stage.</p>
          </div>
          <div>
            <label className={labelCls}>Invite Daily Cap</label>
            <input type="number" value={form.invite_daily_cap || 0} onChange={(e) => update('invite_daily_cap', parseInt(e.target.value) || 0)} className={inputClassName} />
            <p className="mt-2 text-[11px] text-slate-400 font-medium">Max invites per account/day.</p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-8">
          <div>
            <label className={labelCls}>Active Hours Start (0-23)</label>
            <input type="number" min="0" max="23" value={form.active_hours_start || 0} onChange={(e) => update('active_hours_start', parseInt(e.target.value) || 0)} className={inputClassName} />
          </div>
          <div>
            <label className={labelCls}>Active Hours End (0-23)</label>
            <input type="number" min="0" max="23" value={form.active_hours_end || 0} onChange={(e) => update('active_hours_end', parseInt(e.target.value) || 0)} className={inputClassName} />
          </div>
        </div>

        <div>
          <label className={labelCls}>AI Screening Prompt</label>
          <textarea
            value={form.screening_prompt || ''}
            onChange={(e) => update('screening_prompt', e.target.value)}
            className={inputClassName + ' min-h-[100px] resize-none'}
            rows={3}
            placeholder="Global filtering instructions..."
          />
        </div>

        <div className="flex items-center justify-between rounded-2xl border border-slate-100 bg-slate-50/50 p-4 dark:border-slate-800 dark:bg-slate-900/40">
          <div>
            <p className="text-sm font-semibold text-slate-900 dark:text-white">Simulation Mode</p>
            <p className="text-xs text-slate-500 mt-0.5">Dry-run mode. No real messages will be sent.</p>
          </div>
          <button
            type="button"
            onClick={() => update('simulation_mode', !form.simulation_mode)}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${form.simulation_mode ? 'bg-brand-500' : 'bg-slate-200 dark:bg-slate-700'}`}
          >
            <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${form.simulation_mode ? 'translate-x-5' : 'translate-x-0'}`} />
          </button>
        </div>

        <div className="pt-4">
          <Button
            type="submit"
            variant="primary"
            size="md"
            icon={Save}
            disabled={!dirty}
            isLoading={updateCampaign.isPending}
          >
            Save Changes
          </Button>
        </div>
      </form>

      <div className="pt-10 border-t border-slate-100 dark:border-slate-800">
        <div className="mb-6">
          <h2 className="text-xs font-bold uppercase tracking-widest text-slate-400">Assigned Sending Nodes</h2>
          <p className="text-sm text-slate-500 mt-1">LinkedIn accounts that will execute this campaign's sequences.</p>
        </div>
        
        <div className="grid gap-3">
          {(linkedinAccountsQuery.data || []).map(acct => (
            <Card key={acct.id} padding="none" className="flex items-center justify-between p-4">
              <div className="flex items-center gap-3">
                <div className="h-8 w-8 rounded-full bg-brand-50 flex items-center justify-center text-brand-600 dark:bg-brand-900/30 dark:text-brand-400">
                  <span className="text-xs font-bold">{acct.name[0]}</span>
                </div>
                <span className="text-sm font-semibold text-slate-900 dark:text-white">{acct.name}</span>
              </div>
              <Button
                variant={assignedIds.has(acct.id) ? 'secondary' : 'primary'}
                size="xs"
                onClick={() => toggleAccount(acct.id)}
              >
                {assignedIds.has(acct.id) ? 'Remove' : 'Assign'}
              </Button>
            </Card>
          ))}
          {linkedinAccountsQuery.data?.length === 0 && (
            <div className="rounded-xl border border-dashed border-slate-200 p-6 text-center dark:border-slate-800">
              <p className="text-sm text-slate-400 mb-3">No LinkedIn accounts connected.</p>
              <Link to="/settings" className="inline-flex items-center gap-1.5 text-xs font-bold text-brand-600 hover:text-brand-700">
                Go to settings <ExternalLink size={12} />
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
