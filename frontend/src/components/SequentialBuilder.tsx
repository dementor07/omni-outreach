import React, { useState, useEffect } from 'react'
import { 
  Plus, Trash2, ChevronUp, ChevronDown, Linkedin, Mail, MessageSquare, 
  Smartphone, Phone, Clock, Zap, Save, Tag, MinusCircle, GitBranch, 
  StopCircle, Webhook, MessageCircle, Brain, Route, Database, 
  Flame, UserCheck, Settings2, Globe
} from 'lucide-react'
import { Node, Edge } from '@xyflow/react'
import { NodeType } from '../hooks/useSequenceSteps'
import { api } from '../api/client'
import Badge from './Badge'
import StepIcon from './StepIcon'
import Button from './Button'
import Card from './Card'
import { Select } from './FilterBar'
import { clsx } from 'clsx'

interface SequentialStep {
  id: string
  type: NodeType
  delay_days: number
}

interface Props {
  nodes: Node[]
  edges: Edge[]
  onSave: (nodes: Node[], edges: Edge[]) => void
  onEditTemplate: (id: string) => void
  isSaving?: boolean
}

const STEP_LABELS: Partial<Record<NodeType, string>> = {
  trigger_start: 'Sequence Start',
  action_linkedin_invite: 'Send Invite',
  action_linkedin_dm: 'LinkedIn DM',
  action_linkedin_inmail: 'InMail',
  action_linkedin_profile_view: 'View Profile',
  action_email: 'Email',
  action_whatsapp: 'WhatsApp',
  action_sms: 'SMS',
  action_instagram: 'Instagram',
  action_telegram: 'Telegram',
  action_voice: 'AI Voice Call',
  action_webhook: 'Webhook / CRM',
  action_add_tag: 'Add Tag',
  action_remove_tag: 'Remove Tag',
  action_enrich: 'Enrich Lead',
  action_hot_lead_alert: 'Hot Lead Alert',
  human_approval: 'Human Approval',
  condition_reply_intent: 'Reply Intent',
  condition_replied: 'If Replied',
  condition_linkedin_distance: 'If 1st Degree',
  condition_tag_exists: 'If Has Tag',
  condition_ai_screen: 'AI Screen',
  condition_lead_source: 'Source Router',
  condition_has_field: 'If Has Field',
  event_invite_accepted: 'Invite Accepted',
  event_email_opened: 'Email Opened',
  event_link_clicked: 'Link Clicked',
  delay: 'Wait',
  split: 'A/B Split',
  end: 'End',
}

const CHANNEL_COLORS: Partial<Record<NodeType, { bg: string, text: string }>> = {
  action_linkedin_invite: { bg: 'bg-brand-50', text: 'text-brand-600' },
  action_linkedin_dm: { bg: 'bg-brand-50', text: 'text-brand-600' },
  action_linkedin_inmail: { bg: 'bg-brand-50', text: 'text-brand-600' },
  action_email: { bg: 'bg-sky-50', text: 'text-sky-600' },
  action_whatsapp: { bg: 'bg-emerald-50', text: 'text-emerald-600' },
  action_sms: { bg: 'bg-violet-50', text: 'text-violet-600' },
  action_voice: { bg: 'bg-violet-50', text: 'text-violet-600' },
  human_approval: { bg: 'bg-teal-50', text: 'text-teal-600' },
  action_hot_lead_alert: { bg: 'bg-rose-50', text: 'text-rose-600' },
}

export default function SequentialBuilder({ nodes, edges, onSave, onEditTemplate, isSaving }: Props) {
  const [voiceAgents, setVoiceAgents] = useState<Array<{ id: string; name: string }>>([])
  const [expandedVoice, setExpandedVoice] = useState<string | null>(null)

  useEffect(() => {
    api.get('/accounts/voice').then(r => setVoiceAgents(r.data)).catch(() => {})
  }, [])

  const getNodeData = (id: string): Record<string, unknown> =>
    ((nodes.find(n => n.id === id)?.data) as Record<string, unknown>) ?? {}

  const steps = React.useMemo(() => {
    return nodes
      .filter(n => n.type !== 'trigger_start')
      .map(n => ({
        id: n.id,
        type: n.type as NodeType,
        delay_days: (n.data as any)?.delay_days || 0
      }))
  }, [nodes])

  const addStep = (type: NodeType) => {
    const newId = `node_${Date.now()}`
    const hasTrigger = nodes.some(n => n.type === 'trigger_start')
    const newNodes = [...nodes]
    const newEdges = [...edges]

    if (!hasTrigger) {
      const trigger: Node = {
        id: 'trigger_start',
        type: 'trigger_start',
        position: { x: 250, y: 0 },
        data: {},
      }
      newNodes.unshift(trigger)
    }

    const lastNode = newNodes[newNodes.length - 1]
    const newNode: Node = {
      id: newId,
      type,
      position: { x: 250, y: newNodes.length * 150 },
      data: { delay_days: type === 'delay' ? 1 : 0 },
    }
    newNodes.push(newNode)

    newEdges.push({
      id: `edge_${lastNode.id}_${newId}`,
      source: lastNode.id,
      target: newId,
      sourceHandle: 'default',
      targetHandle: 'default',
    })

    onSave(newNodes, newEdges)
  }

  const removeStep = (id: string) => {
    const newNodes = nodes.filter(n => n.id !== id)
    const actionNodes = newNodes.filter(n => n.type !== 'trigger_start')
    const startNode = newNodes.find(n => n.type === 'trigger_start')
    const newEdges: Edge[] = []
    let prev = startNode
    actionNodes.forEach((node) => {
      if (prev) {
        newEdges.push({
          id: `edge_${prev.id}_${node.id}`,
          source: prev.id,
          target: node.id,
          sourceHandle: 'default',
          targetHandle: 'default'
        })
      }
      prev = node
    })
    onSave(newNodes, newEdges)
  }

  const moveStep = (index: number, direction: 'up' | 'down') => {
    const actionNodes = nodes.filter(n => n.type !== 'trigger_start')
    const startNode = nodes.find(n => n.type === 'trigger_start')
    const newIndex = direction === 'up' ? index - 1 : index + 1
    if (newIndex < 0 || newIndex >= actionNodes.length) return
    const newActionNodes = [...actionNodes]
    const [moved] = newActionNodes.splice(index, 1)
    newActionNodes.splice(newIndex, 0, moved)
    const newNodes = startNode ? [startNode, ...newActionNodes] : newActionNodes
    const newEdges: Edge[] = []
    let prev = startNode
    newActionNodes.forEach((node) => {
      if (prev) {
        newEdges.push({
          id: `edge_${prev.id}_${node.id}`,
          source: prev.id,
          target: node.id,
          sourceHandle: 'default',
          targetHandle: 'default'
        })
      }
      prev = node
    })
    onSave(newNodes, newEdges)
  }

  const updateStep = (id: string, data: any) => {
    const newNodes = nodes.map(n => {
      if (n.id === id) {
        return { ...n, data: { ...n.data, ...data } }
      }
      return n
    })
    onSave(newNodes, edges)
  }

  return (
    <div className="mx-auto max-w-4xl space-y-12 py-8">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-[20px] font-bold tracking-tight text-slate-900 dark:text-white">Linear Sequence</h3>
          <p className="mt-1 text-sm text-slate-500">Define the execution order of your outreach pipeline.</p>
        </div>
        <Button
          variant="primary"
          size="md"
          icon={Save}
          isLoading={isSaving}
          onClick={() => onSave(nodes, edges)}
        >
          Save Changes
        </Button>
      </div>

      <div className="relative space-y-6">
        {/* The Vertical Pipeline Line */}
        <div className="absolute left-[39px] top-6 bottom-6 w-0.5 bg-slate-100 dark:bg-slate-800" />

        {/* Start Marker */}
        <div className="relative z-10 flex items-center gap-6">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-full bg-white border-4 border-slate-50 shadow-sm dark:bg-slate-950 dark:border-slate-900">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-50 text-brand-600 shadow-inner dark:bg-brand-900/30">
              <Zap size={20} fill="currentColor" />
            </div>
          </div>
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-brand-500">Trigger</p>
            <h4 className="text-base font-bold text-slate-900 dark:text-white">Sequence Activated</h4>
          </div>
        </div>

        {steps.length === 0 ? (
          <div className="ml-24 rounded-2xl border-2 border-dashed border-slate-200 bg-white/50 p-12 text-center dark:border-slate-800 dark:bg-slate-900/30">
            <h4 className="font-bold text-slate-400">Empty Pipeline</h4>
            <p className="mt-1 text-sm text-slate-400">Add an action from the tiles below to start.</p>
          </div>
        ) : (
          steps.map((step, i) => (
            <React.Fragment key={step.id}>
              <div className="relative z-10 flex items-start gap-6 group">
                <div className="flex h-20 w-20 shrink-0 flex-col items-center justify-center">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-white bg-slate-100 text-xs font-black text-slate-400 shadow-sm transition-all group-hover:bg-brand-500 group-hover:text-white dark:border-slate-950 dark:bg-slate-800">
                    {i + 1}
                  </div>
                </div>

                <Card padding="none" className="flex-1 transition-all group-hover:border-brand-200 group-hover:shadow-lg group-hover:shadow-brand-500/5">
                  <div className="flex items-center gap-4 p-5">
                    <div className={clsx(
                      'flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl',
                      CHANNEL_COLORS[step.type]?.bg || 'bg-slate-50 dark:bg-slate-800',
                      CHANNEL_COLORS[step.type]?.text || 'text-slate-500'
                    )}>
                      <StepIcon type={step.type} />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="text-[15px] font-bold text-slate-900 dark:text-white truncate">
                          {STEP_LABELS[step.type] ?? step.type}
                        </p>
                        {step.type === 'action_voice' && <Badge label="AI Voice" variant="violet" size="xs" />}
                      </div>
                      
                      <div className="mt-1">
                        {step.type === 'delay' ? (
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Wait</span>
                            <input 
                              type="number"
                              min="1"
                              value={step.delay_days}
                              onChange={(e) => updateStep(step.id, { delay_days: parseInt(e.target.value) || 1 })}
                              className="w-12 rounded-lg border border-slate-200 bg-slate-50 py-0.5 text-center text-xs font-bold text-slate-900 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-800 dark:text-white"
                            />
                            <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Days</span>
                          </div>
                        ) : (
                          <p className="text-[11px] font-medium text-slate-400">Executes after previous step completion</p>
                        )}
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <div className="flex flex-col border-r border-slate-100 pr-2 mr-1 dark:border-slate-800">
                        <button onClick={() => moveStep(i, 'up')} disabled={i === 0} className="p-1 text-slate-300 hover:text-brand-500 disabled:opacity-20 transition-colors"><ChevronUp size={16} /></button>
                        <button onClick={() => moveStep(i, 'down')} disabled={i === steps.length - 1} className="p-1 text-slate-300 hover:text-brand-500 disabled:opacity-20 transition-colors"><ChevronDown size={16} /></button>
                      </div>

                      {step.type === 'action_voice' ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          icon={Settings2}
                          onClick={() => setExpandedVoice(expandedVoice === step.id ? null : step.id)}
                        >
                          Config
                        </Button>
                      ) : step.type.startsWith('action_') ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() => onEditTemplate(step.id)}
                        >
                          Edit
                        </Button>
                      ) : null}

                      <button
                        onClick={() => removeStep(step.id)}
                        className="rounded-xl p-2 text-slate-300 transition-colors hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-900/20"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </div>
                  
                  {step.type === 'action_voice' && expandedVoice === step.id && (
                    <div className="border-t border-slate-100 bg-slate-50/50 p-6 dark:border-slate-800 dark:bg-slate-950/30">
                      <VoiceNodeConfig
                        nodeData={getNodeData(step.id)}
                        voiceAgents={voiceAgents}
                        onUpdate={(data) => updateStep(step.id, data)}
                      />
                    </div>
                  )}
                </Card>
              </div>
            </React.Fragment>
          ))
        )}

        {/* End Marker */}
        <div className="relative z-10 flex items-center gap-6">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center">
            <div className="h-4 w-4 rounded-full border-4 border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950" />
          </div>
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-400">End of sequence</p>
        </div>
      </div>

      <div className="space-y-6 pt-12 border-t border-slate-100 dark:border-slate-800">
        <div>
          <h4 className="text-[11px] font-bold uppercase tracking-[0.15em] text-slate-400">Available Actions</h4>
          <p className="mt-1 text-sm text-slate-500">Inject steps into your sequence to build your outreach strategy.</p>
        </div>
        
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <ActionTile icon={<Linkedin size={18} />} label="Send Invite" sub="LinkedIn" onClick={() => addStep('action_linkedin_invite')} tone="brand" />
          <ActionTile icon={<Linkedin size={18} />} label="LinkedIn DM" sub="Direct Message" onClick={() => addStep('action_linkedin_dm')} tone="brand" />
          <ActionTile icon={<Linkedin size={18} />} label="InMail" sub="Sales Nav" onClick={() => addStep('action_linkedin_inmail')} tone="brand" />
          <ActionTile icon={<Mail size={18} />} label="Email" sub="SMTP/Outlook" onClick={() => addStep('action_email')} tone="info" />
          <ActionTile icon={<MessageSquare size={18} />} label="WhatsApp" sub="Meta API" onClick={() => addStep('action_whatsapp')} tone="success" />
          <ActionTile icon={<MessageCircle size={18} />} label="SMS" sub="Twilio" onClick={() => addStep('action_sms')} tone="violet" />
          <ActionTile icon={<Phone size={18} />} label="AI Voice" sub="Retell API" onClick={() => addStep('action_voice')} tone="violet" />
          <ActionTile icon={<Webhook size={18} />} label="Webhook" sub="External CRM" onClick={() => addStep('action_webhook')} tone="info" />
          <ActionTile icon={<Clock size={18} />} label="Wait" sub="Delay Execution" onClick={() => addStep('delay')} tone="amber" />
          <ActionTile icon={<Brain size={18} />} label="AI Screen" sub="LLM Filter" onClick={() => addStep('condition_ai_screen')} tone="violet" />
          <ActionTile icon={<UserCheck size={18} />} label="Approval" sub="Human Loop" onClick={() => addStep('human_approval')} tone="success" />
          <ActionTile icon={<Flame size={18} />} label="Hot Alert" sub="Slack Notify" onClick={() => addStep('action_hot_lead_alert')} tone="rose" />
          <ActionTile icon={<Tag size={18} />} label="Add Tag" sub="Segmenting" onClick={() => addStep('action_add_tag')} tone="neutral" />
          <ActionTile icon={<Database size={18} />} label="Enrich" sub="Data Lookup" onClick={() => addStep('action_enrich')} tone="brand" />
          <ActionTile icon={<GitBranch size={18} />} label="Router" sub="Logic Flow" onClick={() => addStep('condition_lead_source')} tone="amber" />
          <ActionTile icon={<StopCircle size={18} />} label="End" sub="Terminate" onClick={() => addStep('end')} tone="rose" />
        </div>
      </div>
    </div>
  )
}

function ActionTile({ icon, label, sub, onClick, tone }: { 
  icon: React.ReactNode, 
  label: string, 
  sub: string, 
  onClick: () => void, 
  tone: 'brand' | 'success' | 'info' | 'violet' | 'amber' | 'rose' | 'neutral'
}) {
  const tones = {
    brand:   'text-brand-600 bg-brand-50 group-hover:bg-brand-500 group-hover:text-white',
    success: 'text-emerald-600 bg-emerald-50 group-hover:bg-emerald-500 group-hover:text-white',
    info:    'text-sky-600 bg-sky-50 group-hover:bg-sky-500 group-hover:text-white',
    violet:  'text-violet-600 bg-violet-50 group-hover:bg-violet-500 group-hover:text-white',
    amber:   'text-amber-600 bg-amber-50 group-hover:bg-amber-500 group-hover:text-white',
    rose:    'text-rose-600 bg-rose-50 group-hover:bg-rose-500 group-hover:text-white',
    neutral: 'text-slate-600 bg-slate-50 group-hover:bg-slate-500 group-hover:text-white',
  }

  return (
    <button
      onClick={onClick}
      className="group flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 transition-all hover:border-brand-200 hover:shadow-xl hover:shadow-brand-500/5 active:scale-[0.98] dark:border-slate-800 dark:bg-slate-900"
    >
      <div className={clsx('flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl transition-colors', tones[tone])}>
        {icon}
      </div>
      <div className="min-w-0 text-left">
        <p className="text-sm font-bold text-slate-900 dark:text-white truncate">{label}</p>
        <p className="text-[11px] font-medium text-slate-400 truncate">{sub}</p>
      </div>
    </button>
  )
}

function VoiceNodeConfig({
  nodeData,
  voiceAgents,
  onUpdate,
}: {
  nodeData: Record<string, unknown>
  voiceAgents: Array<{ id: string; name: string }>
  onUpdate: (data: Record<string, unknown>) => void
}) {
  const [rows, setRows] = useState<Array<{ retellVar: string; leadField: string }>>(() => {
    const mappings = (nodeData.field_mappings as Record<string, string>) ?? {}
    return Object.entries(mappings).map(([k, v]) => ({ retellVar: k, leadField: v }))
  })

  const commit = (next: typeof rows) => {
    const field_mappings = Object.fromEntries(
      (next ?? []).filter(r => r.retellVar.trim()).map(r => [r.retellVar.trim(), r.leadField])
    )
    onUpdate({ field_mappings })
  }

  const addRow = () => {
    const next = [...(rows ?? []), { retellVar: '', leadField: 'name' }]
    setRows(next)
  }

  const updateRow = (idx: number, patch: Partial<{ retellVar: string; leadField: string }>) => {
    const next = (rows ?? []).map((r, i) => i === idx ? { ...r, ...patch } : r)
    setRows(next)
    if (patch.leadField !== undefined) commit(next)
  }

  const removeRow = (idx: number) => {
    const next = (rows ?? []).filter((_, i) => i !== idx)
    setRows(next)
    commit(next)
  }

  const inputCls = "w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-800 outline-none focus:border-brand-400 focus:ring-4 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:focus:ring-brand-900/20"
  const labelCls = "mb-2 block text-[11px] font-bold uppercase tracking-widest text-slate-400"

  return (
    <div className="space-y-6">
      <div>
        <label className={labelCls}>Voice Agent Provider</label>
        <Select
          value={(nodeData.voice_agent_id as string) || ''}
          onChange={v => onUpdate({ voice_agent_id: v })}
          className="w-full"
        >
          <option value="">— select agent —</option>
          {voiceAgents.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className={labelCls}>Lead Field Mappings</label>
          <button type="button" onClick={addRow} className="text-[11px] font-bold text-brand-600 hover:underline">+ Add Mapping</button>
        </div>
        <div className="space-y-2.5">
          {rows.map((row, i) => (
            <div key={i} className="flex items-center gap-3">
              <input
                value={row.retellVar}
                onChange={e => updateRow(i, { retellVar: e.target.value })}
                onBlur={() => commit(rows)}
                placeholder="script_var"
                className="flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-800 outline-none focus:border-brand-400 dark:border-slate-700 dark:bg-slate-900 dark:text-white"
              />
              <span className="text-slate-300">→</span>
              <Select
                value={row.leadField}
                onChange={v => updateRow(i, { leadField: v })}
                className="flex-1"
                size="sm"
              >
                {LEAD_FIELDS.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
              </Select>
              <button onClick={() => removeRow(i)} className="p-2 text-slate-300 hover:text-rose-500"><Trash2 size={16} /></button>
            </div>
          ))}
          {rows.length === 0 && <p className="py-4 text-center text-xs italic text-slate-400 border border-dashed border-slate-200 rounded-xl">No mappings defined</p>}
        </div>
      </div>
    </div>
  )
}

const LEAD_FIELDS = [
  { value: 'name',         label: 'Full Name' },
  { value: 'email',        label: 'Email' },
  { value: 'phone',        label: 'Phone' },
  { value: 'company_name', label: 'Company' },
  { value: 'job_title',    label: 'Job Title' },
  { value: 'linkedin_url', label: 'LinkedIn URL' },
  { value: 'location',     label: 'Location' },
]
