import { Linkedin, Mail, MessageSquare, Instagram, Send, Phone, Clock, Zap, Tag, MinusCircle, GitBranch, Bell, StopCircle, Shuffle, Webhook, MessageCircle, Brain, Route, Database, Flame, UserCheck } from 'lucide-react'
import { type NodeType } from '../hooks/useSequenceSteps'

export default function StepIcon({ type }: { type: NodeType }) {
  switch (type) {
    case 'action_linkedin_invite':       return <Linkedin size={20} className="text-sky-600" />
    case 'action_linkedin_dm':           return <Linkedin size={20} className="text-sky-500" />
    case 'action_linkedin_inmail':       return <Linkedin size={20} className="text-indigo-500" />
    case 'action_linkedin_profile_view': return <Linkedin size={20} className="text-slate-400" />
    case 'action_email':                 return <Mail size={20} className="text-slate-500" />
    case 'action_whatsapp':              return <MessageSquare size={20} className="text-emerald-500" />
    case 'action_sms':                   return <MessageCircle size={20} className="text-teal-500" />
    case 'action_instagram':             return <Instagram size={20} className="text-pink-500" />
    case 'action_telegram':              return <Send size={20} className="text-blue-400" />
    case 'action_voice':                 return <Phone size={20} className="text-indigo-500" />
    case 'action_webhook':               return <Webhook size={20} className="text-orange-500" />
    case 'action_add_tag':               return <Tag size={20} className="text-slate-500" />
    case 'action_remove_tag':            return <MinusCircle size={20} className="text-slate-400" />
    case 'action_enrich':                return <Database size={20} className="text-indigo-500" />
    case 'condition_replied':
    case 'condition_linkedin_distance':
    case 'condition_tag_exists':         return <GitBranch size={20} className="text-amber-500" />
    case 'condition_ai_screen':          return <Brain size={20} className="text-violet-500" />
    case 'condition_lead_source':        return <Route size={20} className="text-cyan-500" />
    case 'condition_has_field':          return <GitBranch size={20} className="text-amber-500" />
    case 'condition_reply_intent':       return <Brain size={20} className="text-violet-500" />
    case 'human_approval':               return <UserCheck size={20} className="text-teal-500" />
    case 'action_hot_lead_alert':        return <Flame size={20} className="text-rose-500" />
    case 'event_invite_accepted':
    case 'event_email_opened':
    case 'event_link_clicked':           return <Bell size={20} className="text-violet-500" />
    case 'delay':                        return <Clock size={20} className="text-amber-500" />
    case 'split':                        return <Shuffle size={20} className="text-purple-500" />
    case 'end':                          return <StopCircle size={20} className="text-rose-500" />
    default:                             return <Zap size={20} />
  }
}
