import React from 'react'
import { Plus, Trash2, ChevronUp, ChevronDown, Linkedin, Mail, MessageSquare, Instagram, Send, Phone, Clock, Zap, Save, Tag, MinusCircle, GitBranch, Bell, StopCircle, Shuffle, Webhook, MessageCircle, Brain, Route, Database, Flame, UserCheck } from 'lucide-react'
import { Node, Edge } from '@xyflow/react'
import { NodeType } from '../hooks/useSequenceSteps'
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
            <div key={step.id} className="group flex items-center gap-4 rounded-3xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-200">
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
                {step.type.startsWith('action_') && (
                  <button
                    onClick={() => onEditTemplate(step.id)}
                    className="rounded-xl bg-slate-50 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-sky-50 hover:text-sky-600"
                  >
                    Edit Template
                  </button>
                )}
                
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
