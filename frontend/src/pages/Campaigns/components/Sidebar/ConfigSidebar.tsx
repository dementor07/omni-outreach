import React, { useEffect, useState } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Node } from '@xyflow/react'
import { X, Zap, Trash2, Settings2 } from 'lucide-react'
import { api } from '../../../../api/client'
import StepIcon from '../../../../components/StepIcon'
import { useToast } from '../../../../components/Toast'
import { useGetTemplate, useUpsertTemplate, type NodeType } from '../../../../hooks/useSequenceSteps'
import { EmailAccount, VoiceAgent, RetellPrompt } from '../../types'
import { labelCls, inputClassName } from './Common'
import { HotLeadAlertConfigPanel } from './HotLeadAlertConfigPanel'

interface ConfigSidebarProps {
  nodeId: string | null
  nodes: Node[]
  onClose: () => void
  onUpdate: (data: any) => void
  onDelete: () => void
}

export function ConfigSidebar({ nodeId, nodes, onClose, onUpdate, onDelete }: ConfigSidebarProps) {
  const node = nodes.find(n => n.id === nodeId)
  // Fall back to data.node_type if xyflow .type wasn't set (e.g. graph rows
  // loaded straight from the backend before the load mapper landed).
  const nodeType = (node?.type ?? ((node?.data as Record<string, unknown> | undefined)?.node_type as string | undefined) ?? '') as NodeType
  const toast = useToast()
  const { id: campaignId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  const templateQuery = useGetTemplate(nodeId || undefined)
  const upsertTemplate = useUpsertTemplate()

  const emailAccountsQuery = useQuery({
    queryKey: ['accounts', 'email'],
    queryFn: async () => (await api.get<EmailAccount[]>('/accounts/email')).data,
  })
  const voiceAgentsQuery = useQuery({
    queryKey: ['accounts', 'voice'],
    queryFn: async () => (await api.get<VoiceAgent[]>('/accounts/voice')).data,
  })

  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')

  const [agentPrompt, setAgentPrompt] = useState<RetellPrompt | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);
  const [promptLoading, setPromptLoading] = useState(false);
  const [promptSaving, setPromptSaving] = useState(false);
  const [flowMeta, setFlowMeta] = useState<{ node_count: number; edge_count: number } | null>(null);

  const selectedVoiceAgentId = (node?.data as any)?.voice_agent_id;
  const mode = (node?.data as any)?.mode || 'standard';

  useEffect(() => {
    setAgentPrompt(null);
    setPromptError(null);
    setPromptSaving(false);
    setFlowMeta(null);
    if (mode !== 'standard' || !selectedVoiceAgentId) return;
    setPromptLoading(true);
    api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
      .then(r => { setAgentPrompt(r.data); setPromptError(null); })
      .catch((err: any) => {
        const status = err?.response?.status;
        if (status === 400) {
          setPromptError('This agent uses Nested Flow and cannot be edited in Standard mode. Switch to Nested Flow mode above.');
        } else {
          toast.error('Failed to load agent prompt');
        }
      })
      .finally(() => setPromptLoading(false));
  }, [selectedVoiceAgentId, mode, toast]);

  useEffect(() => {
    if (mode !== 'flow' || !selectedVoiceAgentId) return;
    api.get(`/accounts/voice/${selectedVoiceAgentId}/flow`)
      .then(r => {
        const flowNodes = r.data.nodes ?? [];
        const flowEdges = flowNodes.flatMap((n: any) => [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])]);
        setFlowMeta({ node_count: flowNodes.length, edge_count: flowEdges.length });
      })
      .catch(() => setFlowMeta(null));
  }, [selectedVoiceAgentId, mode, location.key]);

  useEffect(() => {
    if (templateQuery.data) {
      setSubject(templateQuery.data.subject ?? '')
      setBody(templateQuery.data.body ?? '')
    } else {
      setSubject('')
      setBody('')
    }
  }, [templateQuery.data])

  if (!node) return null

  const isEmail = nodeType === 'action_email'
  const isVoice = nodeType === 'action_voice'
  const isDelay = nodeType === 'delay'
  const isTagNode = nodeType === 'action_add_tag' || nodeType === 'action_remove_tag' || nodeType === 'condition_tag_exists'
  const needsTemplate = (nodeType as string).startsWith('action_') && nodeType !== 'action_linkedin_invite' && nodeType !== 'action_voice' && !isTagNode

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between p-6 border-b border-slate-100">
        <h3 className="text-sm font-black uppercase tracking-widest text-slate-900">Module Config</h3>
        <button aria-label="Close module config" onClick={onClose} className="p-2 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-900 transition-all"><X size={18} /></button>
      </div>

      <div className="flex-1 overflow-auto p-6 space-y-8 scrollbar-hide">
        {isVoice && (
          <div>
            <label className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-3 block">Operation Mode</label>
            <div className="grid grid-cols-2 gap-2 p-1 bg-slate-50 rounded-xl ring-1 ring-slate-900/5">
              <button 
                onClick={() => onUpdate({ mode: 'standard' })}
                className={`py-2 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${((node.data as any).mode || 'standard') === 'standard' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}
              >
                Standard
              </button>
              <button 
                onClick={() => onUpdate({ mode: 'flow' })}
                className={`py-2 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${((node.data as any).mode || 'standard') === 'flow' ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-400 hover:text-slate-600'}`}
              >
                Nested Flow
              </button>
            </div>
          </div>
        )}

        <div>
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-400 mb-2 block">Module Type</label>
          <div className="flex items-center gap-3 bg-slate-50 p-4 rounded-2xl ring-1 ring-slate-900/5">
            <StepIcon type={nodeType} />
            <span className="text-sm font-bold text-slate-900 capitalize">{nodeType.replace('action_', '').replace('_', ' ')}</span>
          </div>
        </div>

        {isDelay && (
          <div className="space-y-4">
            <div>
              <label className={labelCls}>Wait Duration</label>
              <div className="flex gap-2">
                <input 
                  type="number" 
                  title="Wait duration value"
                  min="1" 
                  value={(node.data as any).delay_value || (node.data as any).delay_days || 1} 
                  onChange={(e) => onUpdate({ delay_value: parseInt(e.target.value) || 1 })}
                  className={inputClassName + ' flex-1'}
                />
                <select
                  aria-label="Wait unit"
                  value={(node.data as any).delay_unit || 'days'}
                  onChange={(e) => onUpdate({ delay_unit: e.target.value })}
                  className={inputClassName + ' w-32'}
                >
                  <option value="minutes">Minutes</option>
                  <option value="hours">Hours</option>
                  <option value="days">Days</option>
                </select>
              </div>
              <p className="mt-2 text-[10px] text-slate-400">Specify how long to wait before moving to the next module.</p>
            </div>
          </div>
        )}

        {nodeType === 'wait_until' && (
          <div className="space-y-4">
            <div>
              <label className={labelCls}>Wait Until Date</label>
              <input
                type="date"
                title="Wait until date"
                value={(node.data as any).wait_until_date || ''}
                onChange={(e) => onUpdate({ wait_until_date: e.target.value })}
                className={inputClassName}
              />
            </div>
            <div>
              <label className={labelCls}>Time of Day</label>
              <input
                type="time"
                title="Time of day"
                value={(node.data as any).wait_until_time || '09:00'}
                onChange={(e) => onUpdate({ wait_until_time: e.target.value })}
                className={inputClassName}
              />
              <p className="mt-1 text-[10px] text-slate-400">Lead proceeds after this datetime (campaign timezone)</p>
            </div>
          </div>
        )}

        {nodeType === 'goal' && (
          <div className="space-y-4">
            <div>
              <label className={labelCls}>Goal Name</label>
              <input
                type="text"
                value={(node.data as any).goal_name || ''}
                onChange={(e) => onUpdate({ goal_name: e.target.value })}
                className={inputClassName}
                placeholder="e.g., Meeting booked, Demo scheduled"
              />
            </div>
            <div>
              <label className={labelCls}>Goal Event Type</label>
              <select
                aria-label="Goal event type"
                value={(node.data as any).goal_event || 'reply'}
                onChange={(e) => onUpdate({ goal_event: e.target.value })}
                className={inputClassName}
              >
                <option value="reply">Reply received</option>
                <option value="positive_reply">Positive reply</option>
                <option value="meeting_booked">Meeting booked</option>
                <option value="link_clicked">Link clicked</option>
                <option value="custom">Custom event</option>
              </select>
              <p className="mt-1 text-[10px] text-slate-400">Lead is marked as converted when this event fires</p>
            </div>
          </div>
        )}

        {isTagNode && (
          <div>
            <label className={labelCls}>Tag Name</label>
            <input 
              type="text" 
              value={(node.data as any).tag || ''} 
              onChange={(e) => onUpdate({ tag: e.target.value })}
              className={inputClassName}
              placeholder="e.g., high-priority"
            />
          </div>
        )}

        {nodeType === 'condition_ai_screen' && (
          <div>
            <label className={labelCls}>Screening Prompt</label>
            <textarea
              value={(node.data as any).screening_prompt || ''}
              onChange={(e) => onUpdate({ screening_prompt: e.target.value })}
              className={inputClassName + ' min-h-[120px]'}
              placeholder="e.g., Accept leads who are VP/Director level at B2B SaaS companies with 50-500 employees. Reject others."
              rows={5}
            />
            <p className="mt-2 text-[10px] text-slate-400">Claude AI will evaluate each lead's headline against this prompt and route to True (ACCEPT) or False (REJECT).</p>
          </div>
        )}

        {nodeType === 'action_webhook' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Webhook URL</label>
              <input
                type="url"
                value={(node.data as any).url || ''}
                onChange={(e) => onUpdate({ url: e.target.value })}
                className={inputClassName}
                placeholder="https://hooks.zapier.com/…"
              />
            </div>
            <div>
              <label className={labelCls}>Method</label>
              <select
                aria-label="HTTP method"
                value={(node.data as any).method || 'POST'}
                onChange={(e) => onUpdate({ method: e.target.value })}
                className={inputClassName}
              >
                <option value="POST">POST</option>
                <option value="PUT">PUT</option>
                <option value="PATCH">PATCH</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Body Template (optional)</label>
              <textarea
                value={(node.data as any).body_template || ''}
                onChange={(e) => onUpdate({ body_template: e.target.value })}
                className={inputClassName + ' min-h-[100px] font-mono text-xs'}
                placeholder="Leave empty to POST the full lead object. Use {{first_name}}, {{email}} …"
                rows={4}
              />
              <p className="mt-2 text-[10px] text-slate-400">If set, the rendered string is wrapped as {`{ "rendered": "…" }`}. Otherwise a full lead JSON is posted.</p>
            </div>
          </div>
        )}

        {nodeType === 'action_data_transform' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Target Variable Name</label>
              <input
                type="text"
                value={(node.data as any).variable_name || ''}
                onChange={(e) => onUpdate({ variable_name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })}
                className={inputClassName}
                placeholder="e.g. clean_company"
              />
              <p className="mt-1 text-[10px] text-slate-400">The variable to create or update. Accessible as {`{{variable_name}}`}.</p>
            </div>
            <div>
              <label className={labelCls}>Transformation Type</label>
              <select
                aria-label="Transform type"
                value={(node.data as any).transform_type || 'ai_extract'}
                onChange={(e) => onUpdate({ transform_type: e.target.value })}
                className={inputClassName}
              >
                <option value="ai_extract">AI Transformation (Claude Haiku)</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Prompt / Instructions</label>
              <textarea
                value={(node.data as any).prompt || ''}
                onChange={(e) => onUpdate({ prompt: e.target.value })}
                className={inputClassName + ' min-h-[100px]'}
                placeholder="Take {{company}} and remove 'Inc.', 'LLC', or 'Corp'. If the name is 'Apple Inc.', just output 'Apple'."
                rows={4}
              />
              <p className="mt-2 text-[10px] text-slate-400">Claude will evaluate the lead's data against this prompt and save the exact output to the variable.</p>
            </div>
          </div>
        )}

        {nodeType === 'action_ai_compose' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Instruction</label>
              <textarea
                value={(node.data as Record<string, unknown>).instruction as string || ''}
                onChange={(e) => onUpdate({ instruction: e.target.value })}
                className={inputClassName + ' min-h-[100px]'}
                placeholder="Write a 2-sentence opener referencing the lead's headline. Mention {{company}} only if useful."
                rows={4}
              />
              <p className="mt-1 text-[10px] text-slate-400">Claude composes a per-lead message from this instruction + the lead's facts.</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Channel hint</label>
                <select
                  aria-label="AI compose channel"
                  value={(node.data as Record<string, unknown>).channel as string || 'email'}
                  onChange={(e) => onUpdate({ channel: e.target.value })}
                  className={inputClassName}
                >
                  <option value="email">Email</option>
                  <option value="linkedin_dm">LinkedIn DM</option>
                  <option value="whatsapp">WhatsApp</option>
                  <option value="sms">SMS</option>
                  <option value="instagram">Instagram</option>
                  <option value="telegram">Telegram</option>
                </select>
              </div>
              <div>
                <label className={labelCls}>Tone</label>
                <select
                  aria-label="AI compose tone"
                  value={(node.data as Record<string, unknown>).tone as string || 'professional'}
                  onChange={(e) => onUpdate({ tone: e.target.value })}
                  className={inputClassName}
                >
                  <option value="professional">Professional</option>
                  <option value="casual">Casual</option>
                  <option value="direct">Direct</option>
                  <option value="warm">Warm</option>
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Max words</label>
                <input
                  type="number"
                  min={20}
                  max={400}
                  aria-label="AI compose max words"
                  placeholder="120"
                  value={(node.data as Record<string, unknown>).max_words as number || 120}
                  onChange={(e) => onUpdate({ max_words: Math.max(20, Math.min(400, Number(e.target.value) || 120)) })}
                  className={inputClassName}
                />
              </div>
              <div>
                <label className={labelCls}>Target variable</label>
                <input
                  type="text"
                  aria-label="AI compose target variable"
                  placeholder="ai_draft"
                  value={(node.data as Record<string, unknown>).target_variable as string || 'ai_draft'}
                  onChange={(e) => onUpdate({ target_variable: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') })}
                  className={inputClassName}
                />
                <p className="mt-1 text-[10px] text-slate-400">Use {`{{${(node.data as Record<string, unknown>).target_variable as string || 'ai_draft'}}}`} downstream.</p>
              </div>
            </div>
          </div>
        )}

        {nodeType === 'action_sms' && (
          <div>
            <label className={labelCls}>SMS Body</label>
            <textarea
              value={(node.data as any).body || ''}
              onChange={(e) => onUpdate({ body: e.target.value })}
              className={inputClassName + ' min-h-[100px]'}
              placeholder="Hi {{first_name}}, quick question about {{company}}…"
              rows={4}
            />
            <p className="mt-2 text-[10px] text-slate-400">Uses Twilio. Set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER to enable. Templates can also be managed via the Template editor.</p>
          </div>
        )}

        {nodeType === 'action_hot_lead_alert' && <HotLeadAlertConfigPanel node={node} onUpdate={onUpdate} />}

        {nodeType === 'human_approval' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Title</label>
              <input
                type="text"
                value={(node.data as any).title || ''}
                onChange={(e) => onUpdate({ title: e.target.value })}
                className={inputClassName}
                placeholder="Approve outreach for this lead"
              />
            </div>
            <div>
              <label className={labelCls}>Payload / Preview (JSON)</label>
              <textarea
                value={(() => {
                  const p = (node.data as any).payload
                  if (!p) return ''
                  return typeof p === 'string' ? p : JSON.stringify(p, null, 2)
                })()}
                onChange={(e) => {
                  try {
                    onUpdate({ payload: JSON.parse(e.target.value || '{}') })
                  } catch {
                    onUpdate({ payload: e.target.value })
                  }
                }}
                className={inputClassName + ' min-h-[120px] font-mono text-xs'}
                placeholder='{"draft_message": "Hi {{first_name}}…", "channel": "email"}'
                rows={5}
              />
              <p className="mt-2 text-[10px] text-slate-400">This JSON is shown in the Approvals inbox so a reviewer can see what's about to go out. Use {`{{lead_field}}`} placeholders — they're rendered at review time.</p>
            </div>
          </div>
        )}

        {nodeType === 'condition_reply_intent' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Reply Intent Router</label>
              <p className="text-[11px] text-slate-500 mb-3">
                After a reply arrives (from <code>event_replied</code> or inline), the classifier labels it.
                Branches: positive / negative / neutral / out_of_office / unsubscribe / bounce / timeout.
              </p>
              <div className="rounded-lg bg-violet-50 p-3 text-[11px] text-violet-900 space-y-1">
                <p><strong>Tip:</strong> unhook branches you don't need. Unconnected outcomes fall through to sequence end.</p>
                <p>Pair with a preceding <code>condition_replied</code> or <code>event_email_opened</code> so this only evaluates once a reply exists.</p>
              </div>
            </div>
            <div>
              <label className={labelCls}>Timeout (Days)</label>
              <input
                type="number"
                title="Timeout in days"
                min="1"
                value={(node.data as any).timeout_days || 7}
                onChange={(e) => onUpdate({ timeout_days: parseInt(e.target.value) || 7 })}
                className={inputClassName}
              />
              <p className="mt-2 text-[10px] text-slate-400">If no reply arrives within this many days after the last message, route to timeout.</p>
            </div>
          </div>
        )}

        {nodeType === 'action_enrich' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Enrichment Source</label>
              <select
                aria-label="Enrichment source"
                value={(node.data as any).enrich_source || ''}
                onChange={(e) => onUpdate({ enrich_source: e.target.value })}
                className={inputClassName}
              >
                <option value="">Select provider...</option>
                <option value="apollo">Apollo.io (email + profile)</option>
                <option value="hunter">Hunter.io (email finder)</option>
                <option value="proxycurl">ProxyCurl (LinkedIn profile)</option>
              </select>
              <p className="mt-2 text-[10px] text-slate-400">Each provider has different inputs — Apollo needs email/linkedin, Hunter needs name+domain, ProxyCurl needs linkedin_url.</p>
            </div>
            <div>
              <label className={labelCls}>Fields to Fill (optional)</label>
              <p className="mb-2 text-[10px] text-slate-400">Only fill these fields on the lead. Leave unchecked to fill any missing field.</p>
              {['email', 'linkedin_url', 'headline', 'company', 'first_name', 'last_name'].map(f => {
                const fields: string[] = (node.data as any).fields || []
                const checked = fields.includes(f)
                return (
                  <label key={f} className="flex items-center gap-3 rounded-xl px-3 py-1.5 hover:bg-slate-50 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        const next = checked ? fields.filter((x: string) => x !== f) : [...fields, f]
                        onUpdate({ fields: next })
                      }}
                      className="h-4 w-4 rounded border-slate-300 text-sky-500 focus:ring-sky-500"
                    />
                    <span className="text-sm text-slate-700">{f}</span>
                  </label>
                )
              })}
            </div>
          </div>
        )}

        {nodeType === 'condition_has_field' && (
          <div>
            <label className={labelCls}>Field to Check</label>
            <select
              aria-label="Field to check"
              value={(node.data as any).field || 'email'}
              onChange={(e) => onUpdate({ field: e.target.value })}
              className={inputClassName}
            >
              <option value="email">email</option>
              <option value="linkedin_url">linkedin_url</option>
              <option value="headline">headline</option>
              <option value="company">company</option>
              <option value="phone">phone</option>
              <option value="first_name">first_name</option>
              <option value="last_name">last_name</option>
            </select>
            <p className="mt-2 text-[10px] text-slate-400">Routes to True if the lead has a value in this field, False otherwise. Use for waterfall enrichment.</p>
          </div>
        )}

        {nodeType === 'condition_lead_source' && (
          <div>
            <label className={labelCls}>Source Handles</label>
            <p className="mb-3 text-[10px] text-slate-400">Select which lead sources get their own output handle. Unselected sources route to "default".</p>
            {['apify_jobs', 'apollo', 'hunter', 'proxycurl', 'github', 'csv_import', 'manual'].map(src => {
              const sources: string[] = (node.data as any).sources || []
              const checked = sources.includes(src)
              return (
                <label key={src} className="flex items-center gap-3 rounded-xl px-3 py-2 hover:bg-slate-50 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = checked ? sources.filter((s: string) => s !== src) : [...sources, src]
                      onUpdate({ sources: next })
                    }}
                    className="h-4 w-4 rounded border-slate-300 text-sky-500 focus:ring-sky-500"
                  />
                  <span className="text-sm font-medium text-slate-700 capitalize">{src.replace('_', ' ')}</span>
                </label>
              )
            })}
          </div>
        )}

        {nodeType === 'condition_field_equals' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Lead Field</label>
              <input
                type="text"
                value={((node.data as Record<string, unknown>).field_name as string) || ((node.data as Record<string, unknown>).field as string) || ''}
                onChange={(e) => onUpdate({ field_name: e.target.value })}
                className={inputClassName}
                placeholder="e.g. industry, company_size, source"
              />
              <p className="mt-1 text-[10px] text-slate-400">Any lead column, or an extra_data key set by an upstream action_data_transform.</p>
            </div>
            <div>
              <label className={labelCls}>Expected values (one per line)</label>
              <textarea
                value={((node.data as Record<string, unknown>).values as string[] || []).join('\n')}
                onChange={(e) => onUpdate({ values: e.target.value.split('\n').map(s => s.trim()).filter(Boolean) })}
                className={inputClassName + ' min-h-[100px] font-mono text-xs'}
                placeholder={'Finance\nHealthcare\nRetail'}
                rows={5}
              />
              <p className="mt-1 text-[10px] text-slate-400">Each value becomes a named output handle. Anything else routes to <code>default</code>.</p>
            </div>
          </div>
        )}

        {nodeType === 'action_agent' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Goal</label>
              <textarea
                value={(node.data as Record<string, unknown>).goal as string || ''}
                onChange={(e) => onUpdate({ goal: e.target.value })}
                className={inputClassName + ' min-h-[100px]'}
                placeholder="Book a 15-minute discovery call. Their company is {{company}}; tailor the pitch."
                rows={4}
              />
              <p className="mt-1 text-[10px] text-slate-400">Plain-English description. The agent picks tools to pursue this goal.</p>
            </div>
            <div>
              <label className={labelCls}>Tools enabled</label>
              <p className="mb-2 text-[10px] text-slate-400">Subset of agent tools the model may invoke.</p>
              {['send_linkedin_dm', 'send_email', 'mark_hot', 'add_tag', 'end_sequence'].map(t => {
                const tools: string[] = ((node.data as Record<string, unknown>).tools as string[]) || []
                const checked = tools.includes(t)
                return (
                  <label key={t} className="flex items-center gap-3 rounded-xl px-3 py-1.5 hover:bg-slate-50 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => onUpdate({ tools: checked ? tools.filter(x => x !== t) : [...tools, t] })}
                      className="h-4 w-4 rounded border-slate-300 text-violet-500 focus:ring-violet-500"
                    />
                    <span className="text-sm font-mono text-slate-700">{t}</span>
                  </label>
                )
              })}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelCls}>Max turns</label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  aria-label="Agent max turns"
                  value={(node.data as Record<string, unknown>).max_turns as number || 10}
                  onChange={(e) => onUpdate({ max_turns: Math.max(1, Math.min(50, Number(e.target.value) || 10)) })}
                  className={inputClassName}
                />
              </div>
              <div>
                <label className={labelCls}>Max tokens</label>
                <input
                  type="number"
                  min={500}
                  max={200000}
                  aria-label="Agent max tokens"
                  value={(node.data as Record<string, unknown>).max_tokens as number || 10000}
                  onChange={(e) => onUpdate({ max_tokens: Math.max(500, Math.min(200000, Number(e.target.value) || 10000)) })}
                  className={inputClassName}
                />
              </div>
            </div>
            <div>
              <label className={labelCls}>Default email account (for send_email)</label>
              <select
                aria-label="Agent default email account"
                value={(node.data as Record<string, unknown>).default_email_account_id as string || ''}
                onChange={(e) => onUpdate({ default_email_account_id: e.target.value })}
                className={inputClassName}
              >
                <option value="">None — agent may not send email</option>
                {(emailAccountsQuery.data || []).map(a => <option key={a.id} value={a.id}>{a.from_name}</option>)}
              </select>
            </div>
          </div>
        )}

        {nodeType === 'control_race' && (
          <div>
            <label className={labelCls}>Number of branches</label>
            <input
              type="number"
              min={2}
              max={5}
              aria-label="Race branch count"
              value={(node.data as Record<string, unknown>).branch_count as number || 2}
              onChange={(e) => onUpdate({ branch_count: Math.max(2, Math.min(5, Number(e.target.value) || 2)) })}
              className={inputClassName}
            />
            <p className="mt-1 text-[10px] text-slate-400">Each branch fires simultaneously. The first to dispatch a successful action wins; the others get cancelled.</p>
          </div>
        )}

        {nodeType === 'event_webhook_received' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Slug (display only)</label>
              <input
                type="text"
                value={(node.data as Record<string, unknown>).slug as string || ''}
                onChange={(e) => onUpdate({ slug: e.target.value })}
                className={inputClassName}
                placeholder="webinar-registered"
              />
              <p className="mt-1 text-[10px] text-slate-400">External systems wake leads parked here by calling <code>POST /webhooks/events/wake</code> with this node's id and the lead id.</p>
            </div>
          </div>
        )}

        {nodeType === 'sticky_note' && (
          <div>
            <label className={labelCls}>Note text</label>
            <textarea
              value={(node.data as Record<string, unknown>).text as string || ''}
              onChange={(e) => onUpdate({ text: e.target.value })}
              className={inputClassName + ' min-h-[120px]'}
              placeholder="Annotate the canvas — sticky notes have no edges and no side effects."
              rows={6}
            />
          </div>
        )}

        {nodeType === 'split' && (
          <div className="space-y-3">
            <div>
              <label className={labelCls}>Arms (one per line)</label>
              <textarea
                value={(() => {
                  const arms = (node.data as Record<string, unknown>).arms as string[] | undefined
                  if (Array.isArray(arms) && arms.length) return arms.join('\n')
                  return 'arm_a\narm_b'
                })()}
                onChange={(e) => {
                  const arms = e.target.value.split('\n').map(s => s.trim()).filter(Boolean)
                  const existing = ((node.data as Record<string, unknown>).weights as Record<string, unknown>) || {}
                  const weights: Record<string, { alpha: number; beta: number }> = {}
                  for (const a of arms) {
                    const w = existing[a] as { alpha?: number; beta?: number } | undefined
                    weights[a] = { alpha: w?.alpha ?? 1, beta: w?.beta ?? 1 }
                  }
                  onUpdate({ arms, weights })
                }}
                className={inputClassName + ' min-h-[100px] font-mono text-xs'}
                rows={5}
                placeholder={'control\nvariant_a\nvariant_b'}
              />
              <p className="mt-1 text-[10px] text-slate-400">Each arm becomes a labeled output handle. Thompson Sampling picks per lead. Defaults to 2 arms.</p>
            </div>
          </div>
        )}

        {isEmail && (
          <div>
            <label className={labelCls}>Sending Account</label>
            <select 
              aria-label="Sending account"
              value={(node.data as any).email_account_id || ''} 
              onChange={(e) => onUpdate({ email_account_id: e.target.value })}
              className={inputClassName}
            >
              <option value="">Select identity...</option>
              {(emailAccountsQuery.data || []).map(a => <option key={a.id} value={a.id}>{a.from_name}</option>)}
            </select>
          </div>
        )}

        {isVoice && (
          <div className="space-y-4">
            <div>
              <label className={labelCls}>Voice Agent</label>
              <select 
                aria-label="Voice agent"
                value={(node.data as any).voice_agent_id || ''} 
                onChange={(e) => onUpdate({ voice_agent_id: e.target.value })}
                className={inputClassName}
              >
                <option value="">Select agent...</option>
                {(voiceAgentsQuery.data || []).map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
            
            {mode === 'standard' && selectedVoiceAgentId && (
              <div className="space-y-4 mt-6">
                {promptLoading ? (
                  <div className="space-y-3 animate-pulse">
                    <div className="h-4 bg-slate-100 rounded w-1/4" />
                    <div className="h-10 bg-slate-50 rounded" />
                    <div className="h-4 bg-slate-100 rounded w-1/4" />
                    <div className="h-32 bg-slate-50 rounded" />
                  </div>
                ) : promptError ? (
                  <div className="rounded-xl bg-rose-950/40 border border-rose-800/50 p-4">
                    <p className="text-[11px] text-rose-300 leading-relaxed">{promptError}</p>
                  </div>
                ) : agentPrompt ? (
                  <>
                    <div>
                      <label className={labelCls}>Begin Message</label>
                      <input
                        title="Begin message"
                        className={inputClassName}
                        value={agentPrompt.begin_message}
                        onChange={e => setAgentPrompt(p => p ? { ...p, begin_message: e.target.value } : p)}
                      />
                    </div>
                    <div>
                      <label className={labelCls}>System Prompt</label>
                      <textarea
                        title="System prompt"
                        className={`${inputClassName} min-h-[200px] resize-none`}
                        value={agentPrompt.general_prompt}
                        onChange={e => setAgentPrompt(p => p ? { ...p, general_prompt: e.target.value } : p)}
                      />
                    </div>
                    <button
                      disabled={promptSaving}
                      onClick={async () => {
                        if (!agentPrompt) return;
                        setPromptSaving(true);
                        try {
                          await api.patch(`/accounts/voice/${selectedVoiceAgentId}/prompt`, {
                            begin_message: agentPrompt.begin_message,
                            general_prompt: agentPrompt.general_prompt,
                          });
                          toast.success('Prompt saved');
                        } catch {
                          toast.error('Failed to save prompt');
                        } finally {
                          setPromptSaving(false);
                        }
                      }}
                      className="w-full btn-tactile bg-slate-900 py-3 text-[10px] font-black uppercase tracking-widest text-white hover:bg-slate-800 disabled:opacity-40"
                    >
                      {promptSaving ? 'Saving...' : 'Save Prompt'}
                    </button>
                  </>
                ) : null}
              </div>
            )}

            {mode === 'flow' && selectedVoiceAgentId && (
              <div className="mt-6 space-y-4">
                <button
                  onClick={() => navigate(`/campaigns/${campaignId}/voice-flow/${selectedVoiceAgentId}`)}
                  className="w-full flex items-center justify-between px-4 py-3 rounded-xl bg-sky-500 text-white text-[10px] font-black uppercase tracking-widest hover:bg-sky-600 transition-all"
                >
                  <span>Open Flow Editor</span>
                  <span className="text-sky-100">→</span>
                </button>
                {flowMeta && (
                  <p className="text-[10px] font-bold text-slate-400 text-center uppercase tracking-widest">
                    {flowMeta.node_count} nodes · {flowMeta.edge_count} edges
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {needsTemplate && (
          <div className="space-y-4 pt-4 border-t border-slate-100">
            {isEmail && (
              <div>
                <label className={labelCls}>Subject Line</label>
                <input title="Subject line" placeholder="Email subject line" value={subject} onChange={(e) => setSubject(e.target.value)} className={inputClassName} />
              </div>
            )}
            <div>
              <label className={labelCls}>Message / Script</label>
              <textarea 
                value={body} 
                onChange={(e) => setBody(e.target.value)} 
                className={`${inputClassName} min-h-[200px] resize-none text-pretty`}
                placeholder="Hi {{first_name}}, ..."
              />
            </div>
            <button 
              onClick={async () => {
                await upsertTemplate.mutateAsync({ node_id: nodeId!, subject: subject || null, body })
                toast.success('Script updated.')
              }}
              disabled={upsertTemplate.isPending}
              className="w-full btn-tactile bg-slate-100 py-3 text-[10px] font-black uppercase tracking-widest text-slate-600 hover:bg-slate-200"
            >
              {upsertTemplate.isPending ? 'Syncing...' : 'Update Script'}
            </button>
          </div>
        )}
      </div>

      <div className="p-6 border-t border-slate-100">
        <button 
          onClick={onDelete}
          className="w-full flex items-center justify-center gap-2 py-3 text-[10px] font-black uppercase tracking-widest text-rose-500 hover:bg-rose-50 rounded-xl transition-all"
        >
          <Trash2 size={14} /> Remove Module
        </button>
      </div>
    </div>
  )
}
