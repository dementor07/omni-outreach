import React from 'react'
import { Plus, Trash2, ChevronUp, ChevronDown, Linkedin, Mail, MessageSquare, Instagram, Send, Phone, Clock, Zap, Save } from 'lucide-react'
import { Node, Edge } from '@xyflow/react'
import { NodeType } from '../hooks/useSequenceSteps'
import Badge from './Badge'

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

export default function SequentialBuilder({ nodes, edges, onSave, onEditTemplate, isSaving }: Props) {
  // Convert nodes/edges back to a linear list for display
  // We look for action nodes and delays, ignoring trigger_start for the simple list view
  const steps = React.useMemo(() => {
    return nodes
      .filter(n => n.type !== 'trigger_start')
      .map(n => ({
        id: n.id,
        type: n.type as NodeType,
        delay_days: n.data?.delay_days || 0
      }))
      // Simple sorting by Y position or similar if needed, 
      // but usually we'll rely on the edges to determine order.
      // For this simplified view, we'll assume linear connection order.
  }, [nodes])

  const addStep = (type: NodeType) => {
    const newId = `node_${Date.now()}`
    const lastNode = nodes.length > 0 ? nodes[nodes.length - 1] : null
    
    const newNode: Node = {
      id: newId,
      type,
      position: { x: 250, y: nodes.length * 150 + 100 },
      data: { delay_days: type === 'delay' ? 1 : 0 }
    }

    const newNodes = [...nodes, newNode]
    const newEdges = [...edges]

    if (lastNode) {
      newEdges.push({
        id: `edge_${lastNode.id}_${newId}`,
        source: lastNode.id,
        target: newId,
        sourceHandle: 'default',
        targetHandle: 'default'
      })
    }

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
                <p className="text-sm font-bold text-slate-900 capitalize">{step.type.replace('action_', '').replace('_', ' ')}</p>
                <p className="text-xs text-slate-400">
                  {step.type === 'delay' ? `Wait ${step.delay_days} days` : 'Immediate action'}
                </p>
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

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <AddButton icon={<Linkedin className="text-sky-500" />} label="LinkedIn DM" onClick={() => addStep('action_linkedin_dm')} />
        <AddButton icon={<Mail className="text-slate-500" />} label="Email" onClick={() => addStep('action_email')} />
        <AddButton icon={<MessageSquare className="text-emerald-500" />} label="WhatsApp" onClick={() => addStep('action_whatsapp')} />
        <AddButton icon={<Clock className="text-amber-500" />} label="Delay" onClick={() => addStep('delay')} />
      </div>
    </div>
  )
}

function StepIcon({ type }: { type: NodeType }) {
  switch (type) {
    case 'action_linkedin_invite':
    case 'action_linkedin_dm': return <Linkedin size={20} className="text-sky-500" />
    case 'action_email': return <Mail size={20} className="text-slate-500" />
    case 'action_whatsapp': return <MessageSquare size={20} className="text-emerald-500" />
    case 'action_instagram': return <Instagram size={20} className="text-pink-500" />
    case 'action_telegram': return <Send size={20} className="text-blue-400" />
    case 'action_voice': return <Phone size={20} className="text-indigo-500" />
    case 'delay': return <Clock size={20} className="text-amber-500" />
    default: return <Zap size={20} />
  }
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
