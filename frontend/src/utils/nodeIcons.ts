import {
  AtSign, Briefcase, Building2, CheckCircle2, CheckSquare, Clock, FileSpreadsheet,
  Filter, Flame, GitBranch, GitMerge, Globe, Hand, Instagram, Linkedin, Mail,
  MessageCircle, MessageSquare, OctagonX, Phone, Repeat, Reply, Search, Send,
  ShieldCheck, Shuffle, Slack, Sparkles, Tag, Target, TrendingUp, UserCheck,
  UserPlus, Users, Webhook,
  type LucideIcon,
} from 'lucide-react'
import type { NodeManifest } from '../api/v2'

/* Every node manifest declares an `icon` (lucide kebab-case name) that the
 * backend ships via /nodes — this maps those names to components so each node
 * gets ITS OWN icon instead of collapsing to the category default (which made
 * the whole palette look identical). Unknown names fall back to the caller's
 * category icon. */
const ICON_BY_NAME: Record<string, LucideIcon> = {
  'at-sign': AtSign,
  briefcase: Briefcase,
  building: Building2,
  'check-circle': CheckCircle2,
  'check-square': CheckSquare,
  clock: Clock,
  csv: FileSpreadsheet,
  filter: Filter,
  flame: Flame,
  'git-branch': GitBranch,
  'git-merge': GitMerge,
  globe: Globe,
  hand: Hand,
  instagram: Instagram,
  linkedin: Linkedin,
  mail: Mail,
  'message-circle': MessageCircle,
  'message-square': MessageSquare,
  'octagon-x': OctagonX,
  phone: Phone,
  repeat: Repeat,
  reply: Reply,
  search: Search,
  send: Send,
  'shield-check': ShieldCheck,
  shuffle: Shuffle,
  slack: Slack,
  sparkles: Sparkles,
  tag: Tag,
  target: Target,
  'trending-up': TrendingUp,
  'user-check': UserCheck,
  'user-plus': UserPlus,
  users: Users,
  webhook: Webhook,
}

/* A handful of types where the manifest icon is ambiguous within its group —
 * e.g. four `search` sources — get a sharper per-type override. */
const ICON_BY_TYPE: Record<string, LucideIcon> = {
  'source.csv': FileSpreadsheet,
  'source.sheets': FileSpreadsheet,
  'source.webhook_in': Webhook,
  'source.naukri': Briefcase,
  'source.indeed': Briefcase,
  'source.linkedin_jobs': Linkedin,
  'source.serper_people': Users,
  'source.agency': Target,
  'channel.telegram': Send,
  'channel.slack': Slack,
  'ai.compose': Sparkles,
  'ai.screen_company': Building2,
  'ai.screen_person': UserCheck,
  'ai.enrich': TrendingUp,
}

export function nodeIcon(manifest: Pick<NodeManifest, 'type' | 'icon'>, fallback: LucideIcon): LucideIcon {
  return ICON_BY_TYPE[manifest.type] ?? ICON_BY_NAME[manifest.icon] ?? fallback
}
