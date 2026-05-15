import { Plus, Zap } from 'lucide-react'
import { NodeType } from '../../../../hooks/useSequenceSteps'
import { NODE_PALETTE } from '../../constants'

interface NodeSelectorProps {
  onAdd: (type: NodeType) => void
}

const GROUPS: { heading: string; types: NodeType[] }[] = [
  { heading: 'LinkedIn',     types: ['action_linkedin_invite', 'action_linkedin_dm', 'action_linkedin_inmail', 'action_linkedin_profile_view'] },
  { heading: 'Messaging',    types: ['action_email', 'action_whatsapp', 'action_sms', 'action_instagram', 'action_telegram'] },
  { heading: 'Intelligence', types: ['action_voice', 'action_enrich', 'action_data_transform'] },
  { heading: 'Actions',      types: ['action_add_tag', 'action_remove_tag', 'action_webhook', 'action_hot_lead_alert'] },
  { heading: 'Conditions',   types: ['condition_replied', 'condition_linkedin_distance', 'condition_tag_exists', 'condition_ai_screen', 'condition_lead_source', 'condition_has_field', 'condition_reply_intent'] },
  { heading: 'Human',        types: ['human_approval'] },
  { heading: 'Events',       types: ['event_invite_accepted', 'event_email_opened', 'event_link_clicked'] },
  { heading: 'Control',      types: ['delay', 'control_parallel_fork', 'split', 'end'] },
]

export function NodeSelector({ onAdd }: NodeSelectorProps) {
  return (
    <div className="absolute left-4 top-4 z-10 flex max-h-[calc(100vh-180px)] w-56 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg dark:border-slate-800 dark:bg-slate-900">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5 dark:border-slate-800">
        <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
          Add module
        </p>
        <Plus size={12} className="text-slate-300 dark:text-slate-600" />
      </div>

      {/* Trigger CTA */}
      <div className="border-b border-slate-100 px-2 py-2 dark:border-slate-800">
        <button
          type="button"
          onClick={() => onAdd('trigger_start')}
          className="flex w-full items-center gap-2 rounded-lg bg-brand-500 px-3 py-2 text-[12px] font-semibold text-white shadow-sm shadow-brand-500/20 transition-colors hover:bg-brand-600"
        >
          <Zap size={13} fill="currentColor" />
          Sequence Start
        </button>
      </div>

      {/* Groups */}
      <div className="flex-1 overflow-y-auto px-1.5 py-2">
        {GROUPS.map(({ heading, types }) => (
          <div key={heading} className="mb-2 last:mb-0">
            <p className="px-2 pb-1 pt-1 text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400 dark:text-slate-500">
              {heading}
            </p>
            <div className="space-y-0.5">
              {types.map((type) => {
                const p = NODE_PALETTE.find((n) => n.type === type)
                if (!p) return null
                return (
                  <button
                    key={type}
                    type="button"
                    onClick={() => onAdd(type)}
                    className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-[12px] font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
                  >
                    <span className={`flex h-5 w-5 shrink-0 items-center justify-center rounded ${p.bg} ${p.color}`}>
                      {p.icon}
                    </span>
                    <span className="truncate">{p.label}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
