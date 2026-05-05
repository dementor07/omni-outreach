import React, { useState, useEffect } from 'react'
import { Plus, Trash2, ChevronUp, ChevronDown, Linkedin, Mail, MessageSquare, Instagram, Send, Phone, Clock, Zap, Save, Tag, MinusCircle, GitBranch, Bell, StopCircle, Shuffle, Webhook, MessageCircle, Brain, Route, Database, Flame, UserCheck, Settings2 } from 'lucide-react'
import { Node, Edge } from '@xyflow/react'
import { NodeType } from '../hooks/useSequenceSteps'
import { api } from '../api/client'
import Badge from './Badge'
import StepIcon from './StepIcon'

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

export default function SequentialBuilder({ nodes, edges, onSave, onEditTemplate, isSaving }: Props) {
  const [voiceAgents, setVoiceAgents] = useState<Array<{ id: string; name: string }>>([])
  const [expandedVoice, setExpandedVoice] = useState<string | null>(null)

  useEffect(() => {
    api.get('/accounts/voice').then(r => setVoiceAgents(r.data)).catch(() => {})
  }, [])

  const getNodeData = (id: string): Record<string, unknown> =>
    ((nodes.find(n => n.id === id)?.data) as Record<string, unknown>) ?? {}

  // Convert nodes/edges back to a linear list for display
  // We look for action nodes and delays, ignoring trigger_start for the simple list view
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
    // Re-wire edges linearly
    const actionNodes = newNodes.filter(n => n.type !== 'trigger_start')
    const startNode = newNodes.find(n => n.type === 'trigger_start')
    
    const newEdges: Edge[] = []
    let prev = startNode
    
    actionNodes.forEach((node, i) => {
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
    
    // Re-wire edges
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
    <div className="flex flex-col gap-6 p-8">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold text-slate-900">Sequence Steps</h3>
          <p className="text-sm text-slate-500">Linear outreach flow. High-to-low execution.</p>
        </div>
        <button
          onClick={() => onSave(nodes, edges)}
          disabled={isSaving}
          className="inline-flex items-center gap-2 rounded-xl bg-sky-500 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-sky-100 transition hover:bg-sky-600 active:scale-95"
        >
          <Save size={18} />
          {isSaving ? 'Saving...' : 'Save Sequence'}
        </button>
      </div>

      <div className="space-y-4">
        {steps.length === 0 ? (
          <div className="rounded-3xl border-2 border-dashed border-slate-200 bg-white p-12 text-center">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50 text-slate-400">
              <Zap size={24} />
            </div>
            <h4 className="mt-4 font-semibold text-slate-900">No steps yet</h4>
            <p className="mt-1 text-sm text-slate-500">Add your first outreach action below.</p>
          </div>
        ) : (
          steps.map((step, i) => (
            <React.Fragment key={step.id}>
            <div className="group flex items-center gap-4 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-200">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-slate-50 text-xs font-bold text-slate-400 group-hover:bg-sky-50 group-hover:text-sky-500">
                {i + 1}
              </div>
              
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-50">
                <StepIcon type={step.type} />
              </div>

              <div className="flex-1">
                <p className="text-sm font-bold text-slate-900">{STEP_LABELS[step.type] ?? step.type}</p>
                {step.type === 'delay' ? (
                  <div className="mt-1 flex items-center gap-2">
                    <span className="text-xs text-slate-400">Wait</span>
                    <input 
                      type="number"
                      min="1"
                      value={step.delay_days}
                      onChange={(e) => updateStep(step.id, { delay_days: parseInt(e.target.value) || 1 })}
                      className="w-12 rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-center text-xs font-bold text-slate-900 focus:border-sky-400 focus:outline-none focus:ring-4 focus:ring-sky-100"
                    />
                    <span className="text-xs text-slate-400">days</span>
                  </div>
                ) : (
                  <p className="text-xs text-slate-400">Immediate action</p>
                )}
              </div>

              <div className="flex items-center gap-2">
                {step.type === 'action_voice' ? (
                  <button
                    onClick={() => setExpandedVoice(expandedVoice === step.id ? null : step.id)}
                    className={`flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold transition-all ${expandedVoice === step.id ? 'bg-sky-100 text-sky-700' : 'bg-slate-50 text-slate-600 hover:bg-sky-50 hover:text-sky-600'}`}
                  >
                    <Settings2 size={13} />
                    Configure
                  </button>
                ) : step.type.startsWith('action_') ? (
                  <button
                    onClick={() => onEditTemplate(step.id)}
                    className="rounded-xl bg-slate-50 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-sky-50 hover:text-sky-600"
                  >
                    Edit Template
                  </button>
                ) : null}
                
                <div className="flex flex-col gap-1">
                  <button onClick={() => moveStep(i, 'up')} disabled={i === 0} className="text-slate-300 hover:text-sky-500 disabled:opacity-20"><ChevronUp size={16} /></button>
                  <button onClick={() => moveStep(i, 'down')} disabled={i === steps.length - 1} className="text-slate-300 hover:text-sky-500 disabled:opacity-20"><ChevronDown size={16} /></button>
                </div>

                <button
                  onClick={() => removeStep(step.id)}
                  className="rounded-xl p-2 text-slate-300 hover:bg-rose-50 hover:text-rose-500"
                >
                  <Trash2 size={18} />
                </button>
              </div>
            </div>
            {step.type === 'action_voice' && expandedVoice === step.id && (
              <VoiceNodeConfig
                nodeData={getNodeData(step.id)}
                voiceAgents={voiceAgents}
                onUpdate={(data) => updateStep(step.id, data)}
              />
            )}
            </React.Fragment>
          ))
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <AddButton icon={<Linkedin className="text-sky-600" />} label="Send Invite"   onClick={() => addStep('action_linkedin_invite')} />
        <AddButton icon={<Linkedin className="text-sky-500" />} label="LinkedIn DM"   onClick={() => addStep('action_linkedin_dm')} />
        <AddButton icon={<Linkedin className="text-indigo-500" />} label="InMail"     onClick={() => addStep('action_linkedin_inmail')} />
        <AddButton icon={<Mail className="text-slate-500" />}    label="Email"        onClick={() => addStep('action_email')} />
        <AddButton icon={<MessageSquare className="text-emerald-500" />} label="WhatsApp" onClick={() => addStep('action_whatsapp')} />
        <AddButton icon={<MessageCircle className="text-teal-500" />} label="SMS"     onClick={() => addStep('action_sms')} />
        <AddButton icon={<Phone className="text-indigo-500" />}  label="AI Voice"     onClick={() => addStep('action_voice')} />
        <AddButton icon={<Webhook className="text-orange-500" />} label="Webhook"    onClick={() => addStep('action_webhook')} />
        <AddButton icon={<Tag className="text-slate-500" />}     label="Add Tag"      onClick={() => addStep('action_add_tag')} />
        <AddButton icon={<MinusCircle className="text-slate-400" />} label="Remove Tag"   onClick={() => addStep('action_remove_tag')} />
        <AddButton icon={<Database className="text-indigo-500" />} label="Enrich Lead"  onClick={() => addStep('action_enrich')} />
        <AddButton icon={<Clock className="text-amber-500" />}   label="Wait"         onClick={() => addStep('delay')} />
        <AddButton icon={<Brain className="text-violet-500" />}   label="AI Screen"    onClick={() => addStep('condition_ai_screen')} />
        <AddButton icon={<Route className="text-cyan-500" />}     label="Source Router" onClick={() => addStep('condition_lead_source')} />
        <AddButton icon={<GitBranch className="text-amber-500" />} label="If Has Field" onClick={() => addStep('condition_has_field')} />
        <AddButton icon={<Brain className="text-violet-500" />} label="Reply Intent" onClick={() => addStep('condition_reply_intent')} />
        <AddButton icon={<UserCheck className="text-teal-500" />} label="Human Approval" onClick={() => addStep('human_approval')} />
        <AddButton icon={<Flame className="text-rose-500" />} label="Hot Lead Alert" onClick={() => addStep('action_hot_lead_alert')} />
        <AddButton icon={<StopCircle className="text-rose-500" />} label="End"        onClick={() => addStep('end')} />
      </div>
    </div>
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

  return (
    <div className="mx-1 mb-2 rounded-2xl border border-sky-100 bg-sky-50/50 p-5 space-y-5">
      {/* Voice agent selector */}
      <div>
        <label className="mb-1.5 block text-[10px] font-black uppercase tracking-widest text-slate-500">
          Voice Agent
        </label>
        <select
          title="Voice agent"
          value={(nodeData.voice_agent_id as string) || ''}
          onChange={e => onUpdate({ voice_agent_id: e.target.value })}
          className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 focus:border-sky-400 focus:outline-none focus:ring-4 focus:ring-sky-100"
        >
          <option value="">— select agent —</option>
          {voiceAgents.map(a => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>

      {/* Variable mappings */}
      <div>
        <div className="mb-1 flex items-center justify-between">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Variable Mappings
          </label>
          <button
            type="button"
            onClick={addRow}
            className="text-xs font-bold text-sky-500 hover:text-sky-700"
          >
            + Add
          </button>
        </div>
        <p className="mb-3 text-[11px] text-slate-400">
          Map <code className="rounded bg-slate-100 px-1">{'{{retell_var}}'}</code> names in your
          Retell script to lead fields. No LLM needed.
        </p>
        {(rows ?? []).length === 0 && (
          <p className="text-xs italic text-slate-400">No mappings. Click + Add to define one.</p>
        )}
        <div className="space-y-2">
          {(rows ?? []).map((row, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                value={row.retellVar}
                onChange={e => updateRow(i, { retellVar: e.target.value })}
                onBlur={() => commit(rows ?? [])}
                placeholder="e.g. first_name"
                className="flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 font-mono text-xs text-slate-800 focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-100"
              />
              <span className="text-slate-300">→</span>
              <select
                title="Lead field"
                value={row.leadField}
                onChange={e => updateRow(i, { leadField: e.target.value })}
                className="flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 focus:border-sky-400 focus:outline-none focus:ring-2 focus:ring-sky-100"
              >
                {LEAD_FIELDS.map(f => (
                  <option key={f.value} value={f.value}>{f.label}</option>
                ))}
              </select>
              <button
                type="button"
                title="Remove mapping"
                onClick={() => removeRow(i)}
                className="shrink-0 text-slate-300 hover:text-rose-400"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
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

function AddButton({ icon, label, onClick }: { icon: React.ReactNode, label: string, onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-white p-4 transition hover:border-sky-400 hover:shadow-md active:scale-95"
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-50">
        {icon}
      </div>
      <span className="text-sm font-bold text-slate-700">{label}</span>
    </button>
  )
}
