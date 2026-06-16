import { Database, Send, Bot, Clock, UserCheck, GitBranch, Sparkles, Webhook, ListChecks, type LucideIcon } from 'lucide-react'

/* Single source of truth for canvas/linear node category visuals. Both the
 * CampaignEditor canvas and the SequentialBuilder linear view import this so a
 * node looks identical in either view (system congruity). Keyed by the
 * UPPERCASE NodeCategory (the wire value is lowercase — callers normalize). */
export interface CategoryVisual {
  icon: LucideIcon
  accent: string
  tint: string
  ring: string
  mini: string
}

export const CATEGORY_VISUAL: Record<string, CategoryVisual> = {
  SOURCE:    { icon: Database,   accent: 'text-sky-600',     tint: 'bg-sky-50 dark:bg-sky-950/40',         ring: 'border-sky-200 dark:border-sky-900',         mini: '#0ea5e9' },
  ENRICH:    { icon: Sparkles,   accent: 'text-violet-600',  tint: 'bg-violet-50 dark:bg-violet-950/40',   ring: 'border-violet-200 dark:border-violet-900',   mini: '#8b5cf6' },
  AI:        { icon: Bot,        accent: 'text-fuchsia-600', tint: 'bg-fuchsia-50 dark:bg-fuchsia-950/40', ring: 'border-fuchsia-200 dark:border-fuchsia-900', mini: '#d946ef' },
  CHANNEL:   { icon: Send,       accent: 'text-emerald-600', tint: 'bg-emerald-50 dark:bg-emerald-950/40', ring: 'border-emerald-200 dark:border-emerald-900', mini: '#10b981' },
  CONDITION: { icon: GitBranch,  accent: 'text-amber-600',   tint: 'bg-amber-50 dark:bg-amber-950/40',     ring: 'border-amber-200 dark:border-amber-900',     mini: '#f59e0b' },
  FLOW:      { icon: Clock,      accent: 'text-rose-600',    tint: 'bg-rose-50 dark:bg-rose-950/40',       ring: 'border-rose-200 dark:border-rose-900',       mini: '#f43f5e' },
  CRM:       { icon: UserCheck,  accent: 'text-indigo-600',  tint: 'bg-indigo-50 dark:bg-indigo-950/40',   ring: 'border-indigo-200 dark:border-indigo-900',   mini: '#6366f1' },
  SINK:      { icon: Webhook,    accent: 'text-orange-600',  tint: 'bg-orange-50 dark:bg-orange-950/40',   ring: 'border-orange-200 dark:border-orange-900',   mini: '#f97316' },
  TRANSFORM: { icon: ListChecks, accent: 'text-teal-600',    tint: 'bg-teal-50 dark:bg-teal-950/40',       ring: 'border-teal-200 dark:border-teal-900',       mini: '#14b8a6' },
}

export function visualFor(category: string): CategoryVisual {
  // NodeCategory is a lowercase StrEnum on the wire ("source", "ai", …);
  // normalize so every category gets its own accent.
  return CATEGORY_VISUAL[category?.toUpperCase()] ?? CATEGORY_VISUAL.SOURCE
}
