import React from 'react'
import { Linkedin, Mail, MessageSquare, Instagram, Send, Phone, Clock, Zap, Tag, MinusCircle, GitBranch, Bell, StopCircle, Shuffle, Webhook, MessageCircle, Brain, Route, Database, Flame, UserCheck } from 'lucide-react'
import { NodeType } from '../../hooks/useSequenceSteps'

export type NodeCategory =
  | 'linkedin'
  | 'messaging'
  | 'intelligence'
  | 'tag'
  | 'webhook'
  | 'alert'
  | 'voice'
  | 'enrich'
  | 'flow'

export const NODE_PALETTE: { type: NodeType; label: string; icon: React.ReactNode; color: string; bg: string; border: string; category?: NodeCategory }[] = [
  { type: 'action_linkedin_invite',       label: 'Send Invite',       icon: <Linkedin size={15} />,       color: 'text-sky-600',     bg: 'bg-sky-50',     border: 'border-sky-200',     category: 'linkedin' },
  { type: 'action_linkedin_dm',            label: 'LinkedIn DM',       icon: <Linkedin size={15} />,       color: 'text-sky-500',     bg: 'bg-sky-50',     border: 'border-sky-200',     category: 'linkedin' },
  { type: 'action_linkedin_inmail',        label: 'InMail',            icon: <Linkedin size={15} />,       color: 'text-indigo-500',  bg: 'bg-indigo-50',  border: 'border-indigo-200',  category: 'linkedin' },
  { type: 'action_linkedin_profile_view',  label: 'View Profile',      icon: <Linkedin size={15} />,       color: 'text-slate-500',   bg: 'bg-slate-50',   border: 'border-slate-200',   category: 'linkedin' },
  { type: 'action_email',                  label: 'Email',             icon: <Mail size={15} />,           color: 'text-slate-600',   bg: 'bg-slate-50',   border: 'border-slate-200',   category: 'messaging' },
  { type: 'action_whatsapp',               label: 'WhatsApp',          icon: <MessageSquare size={15} />,  color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', category: 'messaging' },
  { type: 'action_sms',                    label: 'SMS',               icon: <MessageCircle size={15} />,  color: 'text-teal-600',    bg: 'bg-teal-50',    border: 'border-teal-200',    category: 'messaging' },
  { type: 'action_instagram',              label: 'Instagram',         icon: <Instagram size={15} />,      color: 'text-pink-500',    bg: 'bg-pink-50',    border: 'border-pink-200',    category: 'messaging' },
  { type: 'action_telegram',               label: 'Telegram',          icon: <Send size={15} />,           color: 'text-blue-500',    bg: 'bg-blue-50',    border: 'border-blue-200',    category: 'messaging' },
  { type: 'action_voice',                  label: 'AI Voice Call',     icon: <Phone size={15} />,          color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200',  category: 'voice' },
  { type: 'action_webhook',                label: 'Webhook / CRM',     icon: <Webhook size={15} />,        color: 'text-orange-600',  bg: 'bg-orange-50',  border: 'border-orange-200',  category: 'webhook' },
  { type: 'action_enrich',                 label: 'Enrich Lead',       icon: <Database size={15} />,       color: 'text-indigo-600',  bg: 'bg-indigo-50',  border: 'border-indigo-200',  category: 'enrich' },
  { type: 'action_data_transform',         label: 'Set Variable / AI', icon: <Brain size={15} />,          color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200', category: 'intelligence' },
  { type: 'action_ai_compose',             label: 'AI Compose',        icon: <Brain size={15} />,          color: 'text-fuchsia-600', bg: 'bg-fuchsia-50', border: 'border-fuchsia-200', category: 'intelligence' },
  { type: 'control_parallel_fork',         label: 'Parallel Fork',     icon: <GitBranch size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200',   category: 'flow' },
  { type: 'action_hot_lead_alert',         label: 'Hot Lead Alert',    icon: <Flame size={15} />,          color: 'text-rose-600',    bg: 'bg-rose-50',    border: 'border-rose-200',    category: 'alert' },
  { type: 'action_add_tag',                label: 'Add Tag',           icon: <Tag size={15} />,            color: 'text-slate-600',   bg: 'bg-slate-50',   border: 'border-slate-200',   category: 'tag' },
  { type: 'action_remove_tag',             label: 'Remove Tag',        icon: <MinusCircle size={15} />,     color: 'text-slate-500',   bg: 'bg-slate-50',   border: 'border-slate-200',   category: 'tag' },
  { type: 'condition_replied',             label: 'If Replied',        icon: <GitBranch size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'condition_linkedin_distance',   label: 'If 1st Degree',     icon: <GitBranch size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'condition_tag_exists',          label: 'If Has Tag',        icon: <GitBranch size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'condition_ai_screen',           label: 'AI Screen',         icon: <Brain size={15} />,          color: 'text-violet-600',  bg: 'bg-violet-50',  border: 'border-violet-200' },
  { type: 'condition_lead_source',         label: 'Source Router',     icon: <Route size={15} />,          color: 'text-cyan-600',    bg: 'bg-cyan-50',    border: 'border-cyan-200' },
  { type: 'condition_has_field',           label: 'If Has Field',      icon: <GitBranch size={15} />,      color: 'text-amber-600',   bg: 'bg-amber-50',   border: 'border-amber-200' },
  { type: 'condition_reply_intent',        label: 'Reply Intent',      icon: <Brain size={15} />,          color: 'text-violet-600',  bg: 'bg-violet-50',  border: 'border-violet-200' },
  { type: 'human_approval',                label: 'Human Approval',    icon: <UserCheck size={15} />,      color: 'text-teal-600',    bg: 'bg-teal-50',    border: 'border-teal-200' },
  { type: 'event_invite_accepted',         label: 'Invite Accepted',   icon: <Bell size={15} />,           color: 'text-violet-500',  bg: 'bg-violet-50',  border: 'border-violet-200' },
  { type: 'event_email_opened',            label: 'Email Opened',      icon: <Bell size={15} />,           color: 'text-violet-500',  bg: 'bg-violet-50',  border: 'border-violet-200' },
  { type: 'event_link_clicked',            label: 'Link Clicked',      icon: <Bell size={15} />,           color: 'text-violet-500',  bg: 'bg-violet-50',  border: 'border-violet-200' },
  { type: 'delay',                         label: 'Wait',              icon: <Clock size={15} />,          color: 'text-slate-400',   bg: 'bg-slate-50',   border: 'border-slate-200' },
  { type: 'wait_until',                    label: 'Wait Until',        icon: <Clock size={15} />,          color: 'text-orange-500',  bg: 'bg-orange-50',  border: 'border-orange-200' },
  { type: 'split',                         label: 'A/B Split',         icon: <Shuffle size={15} />,        color: 'text-purple-600',  bg: 'bg-purple-50',  border: 'border-purple-200' },
  { type: 'goal',                          label: 'Goal',              icon: <Zap size={15} />,            color: 'text-emerald-600', bg: 'bg-emerald-50', border: 'border-emerald-200' },
  { type: 'end',                           label: 'End',               icon: <StopCircle size={15} />,     color: 'text-rose-600',    bg: 'bg-rose-50',    border: 'border-rose-400' },
]
