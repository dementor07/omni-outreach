import React, { FormEvent } from 'react'
import { Clock, Zap } from 'lucide-react'
import { inputClassName } from '../Sidebar/Common'
import type { CampaignPayload } from '../../types'

interface CampaignFormProps {
  form: CampaignPayload
  onChange: (form: CampaignPayload) => void
  onSubmit: (e: FormEvent) => void
  busy: boolean
  submitLabel: string
}

export function CampaignForm({ form, onChange, onSubmit, busy, submitLabel }: CampaignFormProps) {
  const update = <K extends keyof CampaignPayload>(key: K, val: CampaignPayload[K]) =>
    onChange({ ...form, [key]: val })
  return (
    <form className="space-y-6" onSubmit={onSubmit}>
      <input value={form.name} onChange={(e) => update('name', e.target.value)} placeholder="Campaign Name" className={inputClassName} required />
      <div className="grid grid-cols-2 gap-4">
        <button type="button" onClick={() => update('sequence_mode', 'sequential')} className={`btn-tactile p-6 border-2 flex flex-col gap-2 ${form.sequence_mode === 'sequential' ? 'border-sky-500 bg-sky-50' : 'border-slate-100 bg-slate-50'}`}>
          <Clock size={20} className={form.sequence_mode === 'sequential' ? 'text-sky-500' : 'text-slate-400'} />
          <span className="text-xs font-black uppercase">Sequential</span>
        </button>
        <button type="button" onClick={() => update('sequence_mode', 'canvas')} className={`btn-tactile p-6 border-2 flex flex-col gap-2 ${form.sequence_mode === 'canvas' ? 'border-sky-500 bg-sky-50' : 'border-slate-100 bg-slate-50'}`}>
          <Zap size={20} className={form.sequence_mode === 'canvas' ? 'text-sky-500' : 'text-slate-400'} />
          <span className="text-xs font-black uppercase">Canvas</span>
        </button>
      </div>
      <button type="submit" disabled={busy} className="btn-tactile w-full bg-sky-500 py-4 text-xs text-white">{busy ? 'Creating...' : submitLabel}</button>
    </form>
  )
}
