import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../../api/client'
import { useToast } from '../../../../components/Toast'
import { CampaignPayload, useGetCampaign, useUpdateCampaign } from '../../../../hooks/useCampaigns'
import { LinkedInAccount } from '../../types'
import { labelCls, inputClassName } from '../Sidebar/Common'

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

  if (campaignQuery.isLoading) return <p className="text-sm text-slate-400">Loading…</p>

  const update = (key: string, val: any) => {
    setForm(prev => ({ ...prev, [key]: val }))
    setDirty(true)
  }

  return (
    <div className="space-y-10 max-w-2xl">
      <form onSubmit={async (e) => { e.preventDefault(); await updateCampaign.mutateAsync({ id: campaignId, payload: form as CampaignPayload }); setDirty(false); toast.success('Saved.'); }} className="space-y-6">
        <div>
          <label className={labelCls}>Campaign Name</label>
          <input value={form.name || ''} onChange={(e) => update('name', e.target.value)} className={inputClassName} required />
        </div>

        <div className="grid grid-cols-2 gap-6">
          <div>
            <label className={labelCls}>Daily Lead Cap</label>
            <input type="number" value={form.daily_lead_cap || 0} onChange={(e) => update('daily_lead_cap', parseInt(e.target.value) || 0)} className={inputClassName} />
            <p className="mt-2 text-[10px] text-slate-400 italic">Hard limit at intake (enforced since Migration 008).</p>
          </div>
          <div>
            <label className={labelCls}>Invite Daily Cap</label>
            <input type="number" value={form.invite_daily_cap || 0} onChange={(e) => update('invite_daily_cap', parseInt(e.target.value) || 0)} className={inputClassName} />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6">
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
          <label className={labelCls}>AI Screening Prompt (Legacy)</label>
          <textarea
            value={form.screening_prompt || ''}
            onChange={(e) => update('screening_prompt', e.target.value)}
            className={inputClassName + ' min-h-[80px]'}
            rows={3}
            placeholder="Instructions for global filtering (use nodes for sequence-level logic)"
          />
        </div>

        <label className="flex items-center gap-3 cursor-pointer">
          <div className={`flex h-5 w-10 items-center rounded-full p-1 transition-colors ${form.simulation_mode ? 'bg-amber-500' : 'bg-slate-200'}`}>
            <div className={`h-3 w-3 rounded-full bg-white transition-transform ${form.simulation_mode ? 'translate-x-5' : ''}`} />
          </div>
          <span className={labelCls + ' mb-0'}>Simulation Mode {form.simulation_mode ? <span className="text-amber-500">(dry-run — no real sends)</span> : ''}</span>
        </label>
        <button type="submit" disabled={!dirty} className="btn-tactile bg-sky-500 px-6 py-2.5 text-xs text-white disabled:opacity-40 shadow-lg shadow-sky-100">Save Changes</button>
      </form>

      <div className="pt-8 border-t border-slate-100">
        <h2 className="text-sm font-black uppercase tracking-widest text-slate-900 mb-4">Assigned Sending Nodes</h2>
        <div className="space-y-2">
          {(linkedinAccountsQuery.data || []).map(acct => (
            <div key={acct.id} className="flex items-center justify-between p-4 rounded-2xl bg-slate-50 ring-1 ring-slate-900/5">
              <span className="text-sm font-bold text-slate-900">{acct.name}</span>
              <button onClick={() => toggleAccount(acct.id)} className={`px-4 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all ${assignedIds.has(acct.id) ? 'bg-emerald-100 text-emerald-700 shadow-sm' : 'bg-slate-200 text-slate-500'}`}>
                {assignedIds.has(acct.id) ? 'Active' : 'Enable'}
              </button>
            </div>
          ))}
          {linkedinAccountsQuery.data?.length === 0 && (
            <p className="text-xs text-slate-400">No LinkedIn accounts found. <Link to="/settings" className="text-sky-600 underline">Add one here</Link>.</p>
          )}
        </div>
      </div>
    </div>
  )
}
