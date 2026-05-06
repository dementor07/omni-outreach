import React from 'react'
import { Zap } from 'lucide-react'
import { NodeType } from '../../../../hooks/useSequenceSteps'
import { NODE_PALETTE } from '../../constants'

interface NodeSelectorProps {
  onAdd: (type: NodeType) => void
}

export function NodeSelector({ onAdd }: NodeSelectorProps) {
  const groups: { heading: string; types: NodeType[] }[] = [
    { heading: 'LinkedIn',   types: ['action_linkedin_invite', 'action_linkedin_dm', 'action_linkedin_inmail', 'action_linkedin_profile_view'] },
    { heading: 'Messaging',  types: ['action_email', 'action_whatsapp', 'action_sms', 'action_instagram', 'action_telegram'] },
    { heading: 'Intelligence', types: ['action_voice', 'action_enrich', 'action_data_transform'] },
    { heading: 'Actions',    types: ['action_add_tag', 'action_remove_tag', 'action_webhook', 'action_hot_lead_alert'] },
    { heading: 'Conditions', types: ['condition_replied', 'condition_linkedin_distance', 'condition_tag_exists', 'condition_ai_screen', 'condition_lead_source', 'condition_has_field', 'condition_reply_intent'] },
    { heading: 'Human',      types: ['human_approval'] },
    { heading: 'Events',     types: ['event_invite_accepted', 'event_email_opened', 'event_link_clicked'] },
    { heading: 'Control',    types: ['delay', 'control_parallel_fork', 'split', 'end'] },
  ]

  return (
    <div className="absolute left-4 top-4 z-10 flex w-52 flex-col rounded-2xl border border-slate-200 bg-white shadow-xl max-h-[calc(100vh-160px)]">
      <p className="shrink-0 px-3 pb-2 pt-3 text-[10px] font-black uppercase tracking-[0.2em] text-slate-400">Add Module</p>
      <button
        onClick={() => onAdd('trigger_start')}
        className="mx-2 mb-1 shrink-0 flex items-center gap-3 rounded-xl bg-slate-900 px-4 py-3 text-xs font-bold text-white transition hover:bg-slate-800"
      >
        <Zap size={14} fill="currentColor" /> Sequence Start
      </button>
      <div className="h-px shrink-0 bg-slate-100 mx-2 my-1" />
      <div className="overflow-y-auto flex-1 pb-2 px-1 scrollbar-hide">
        {groups.map(({ heading, types }) => (
          <div key={heading} className="mb-1">
            <p className="px-3 pt-2 pb-1 text-[9px] font-black uppercase tracking-[0.18em] text-slate-300">{heading}</p>
            {types.map((type) => {
              const p = NODE_PALETTE.find(n => n.type === type)!
              return (
                <button
                  key={type}
                  onClick={() => onAdd(type)}
                  className={`flex w-full items-center gap-3 rounded-xl border border-transparent px-3 py-2 text-xs font-bold transition hover:border-slate-200 hover:bg-slate-50 ${p.color}`}
                >
                  {p.icon} {p.label}
                </button>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
