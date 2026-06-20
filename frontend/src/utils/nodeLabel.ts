/* Human-readable names for node types and their output handles.
 *
 * The canvas, palette, linear builder, config panel, and lead views all showed
 * raw machine types ("flow.for_each", "ai.screen_company", "source.ats") and
 * handle ids ("on_error", "empty") — fine for the engine, hostile to a human.
 * This is the single source of truth that turns them into plain English.
 *
 * Unknown types fall back to a prettified type tail (so a newly-added node still
 * reads reasonably before it's added here). */

const NODE_LABELS: Record<string, string> = {
  // Sources — job boards / discovery
  'source.csv': 'CSV import',
  'source.webhook_in': 'Inbound webhook',
  'source.naukri': 'Naukri jobs',
  'source.indeed': 'Indeed jobs',
  'source.linkedin_jobs': 'LinkedIn jobs',
  'source.greenhouse': 'Greenhouse',
  'source.ashby': 'Ashby',
  'source.smartrecruiters': 'SmartRecruiters',
  'source.bamboohr': 'BambooHR',
  'source.workday': 'Workday',
  'source.icims': 'iCIMS',
  'source.lever': 'Lever',
  'source.workable': 'Workable',
  'source.recruitee': 'Recruitee',
  'source.personio': 'Personio',
  'source.rippling': 'Rippling',
  'source.breezy': 'Breezy',
  'source.searxng': 'Web search (free)',
  'source.serper_search': 'Web search (Serper)',
  'source.apollo': 'Apollo',
  'source.clutch': 'Clutch directory',
  'source.serper_people': 'Find people (Serper)',
  'source.searxng_people': 'Find people (free)',

  // AI
  'ai.compose': 'AI compose message',
  'ai.screen_company': 'AI screen company',
  'ai.screen_person': 'AI screen person',
  'ai.enrich': 'AI enrich',

  // Channels
  'channel.email': 'Send email',
  'channel.sms': 'Send SMS',
  'channel.voice': 'AI voice call',
  'channel.linkedin': 'LinkedIn message',
  'channel.whatsapp': 'WhatsApp message',
  'channel.instagram': 'Instagram DM',
  'channel.telegram': 'Telegram message',
  'channel.slack': 'Slack message',
  'channel.webhook_out': 'Outbound webhook',

  // Conditions
  'condition.company_filter': 'Filter companies',
  'condition.field_match': 'If field matches',
  'condition.has_tag': 'If has tag',
  'condition.replied': 'If replied',
  'condition.verify_person': 'Verify person',

  // Flow
  'flow.delay': 'Wait (delay)',
  'flow.wait_until': 'Wait until',
  'flow.for_each': 'For each',
  'flow.split': 'Split (A/B)',
  'flow.race': 'Race',
  'flow.join': 'Join',
  'flow.goal': 'Goal reached',
  'flow.end': 'End sequence',
  'flow.human_approval': 'Human approval',

  // CRM
  'crm.add_tag': 'Add tag',
  'crm.remove_tag': 'Remove tag',
  'crm.create_contact': 'Create contact',
  'crm.resolve_company': 'Resolve company',
  'crm.create_deal': 'Create deal',
  'crm.update_deal': 'Update deal',
  'crm.create_task': 'Create task',
  'crm.hot_lead_alert': 'Hot-lead alert',
}

/** Human name for a node type, e.g. "flow.for_each" → "For each". */
export function nodeLabel(type: string): string {
  if (NODE_LABELS[type]) return NODE_LABELS[type]
  const tail = type.split('.').slice(1).join('.') || type
  return tail.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase())
}

const HANDLE_LABELS: Record<string, string> = {
  default: 'Then',
  on_error: 'On error',
  rejected: 'Rejected',
  accepted: 'Accepted',
  timeout: 'Timed out',
  empty: 'No results',
  true: 'Yes',
  false: 'No',
  matched: 'Matched',
  unmatched: 'No match',
  replied: 'Replied',
  no_reply: 'No reply',
  has_tag: 'Has tag',
  no_tag: 'No tag',
  verified: 'Verified',
  unverified: 'Not verified',
  won: 'Won',
  lost: 'Lost',
}

/** Human name for an output handle, e.g. "on_error" → "On error". */
export function handleLabel(name: string): string {
  if (HANDLE_LABELS[name]) return HANDLE_LABELS[name]
  return name.replace(/_/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase())
}

/** Human label for a node category (UPPER or lower wire value). */
export function categoryLabel(category: string): string {
  const c = category.toUpperCase()
  const map: Record<string, string> = {
    SOURCE: 'Sources',
    ENRICH: 'Enrichment',
    AI: 'AI',
    CHANNEL: 'Channels',
    CONDITION: 'Conditions',
    FLOW: 'Flow & timing',
    CRM: 'CRM actions',
    SINK: 'Outputs',
    TRANSFORM: 'Transform',
  }
  return map[c] ?? category
}
