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
  'source.sheets': 'Google Sheets import',
  'source.producthunt': 'Product Hunt',
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
  'source.linkedin_search': 'LinkedIn search (Unipile)',
  'source.linkfinder_leads': 'Leads finder AI (LinkFinder)',
  'source.linkfinder_employees': 'Company employees (LinkFinder)',
  'source.linkfinder_post_reactions': 'Post reactions (LinkFinder)',

  // LinkFinder enrichment nodes
  'linkfinder.company_website': 'Company website (LinkFinder)',
  'linkfinder.company_phone': 'Company phone (LinkFinder)',
  'linkfinder.company_email': 'Company email (LinkFinder)',
  'linkfinder.company_employee_count': 'Company employee count (LinkFinder)',
  'linkfinder.company_linkedin': 'Company LinkedIn (LinkFinder)',
  'linkfinder.profile_info': 'Profile info (LinkFinder)',
  'linkfinder.profile_email': 'Email from LinkedIn (LinkFinder)',
  'linkfinder.profile_phone': 'Phone from LinkedIn (LinkFinder)',
  'linkfinder.company_page_info': 'Company page info (LinkFinder)',
  'linkfinder.company_page_employees': 'Company page employees (LinkFinder)',
  'linkfinder.name_to_linkedin': 'Name to LinkedIn (LinkFinder)',
  'linkfinder.email_to_linkedin': 'Email to LinkedIn (LinkFinder)',
  'linkfinder.instagram_info': 'Instagram info (LinkFinder)',

  // AI
  'ai.compose': 'AI compose message',
  'ai.screen_company': 'AI screen company',
  'ai.screen_person': 'AI screen person',
  'ai.enrich': 'Enrichment provider',

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
  'channel.n8n': 'n8n workflow',
  'channel.linkedin_react_post': 'React to LinkedIn post',
  'channel.linkedin_comment_post': 'Comment on LinkedIn post',
  'channel.linkedin_endorse': 'Endorse LinkedIn skill',
  'channel.linkedin_follow': 'Follow LinkedIn member',
  'channel.message_react': 'React to message',
  'channel.invite_cancel': 'Cancel LinkedIn invite',
  'enrich.linkedin_company': 'LinkedIn company profile (Unipile)',
  'enrich.linkedin_member': 'LinkedIn profile (Unipile)',

  // Conditions
  'condition.company_filter': 'Filter companies',
  'condition.field_match': 'If field matches',
  'condition.rules': 'Rules',
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
  'flow.continue': 'Continue with enriched lead',

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

const EVENT_LABELS: Record<string, string> = {
  'contact.created': 'Contact created',
  'contact.updated': 'Contact updated',
  'email.sent': 'Email sent',
  'email.opened': 'Email opened',
  'email.clicked': 'Email link clicked',
  'email.replied': 'Replied to email',
  'message.received': 'Reply received',
  'lead.created': 'Lead created',
  'lead.goal_reached': 'Goal reached',
  'lead.sequence_ended': 'Sequence ended',
  'deal.created': 'Deal created',
  'deal.updated': 'Deal updated',
  'task.created': 'Task created',
  'approval.requested': 'Approval requested',
  'approval.resolved': 'Approval resolved',
}

/** Human label for an event_type, e.g. "email.sent" → "Email sent". */
export function eventLabel(eventType: string): string {
  if (EVENT_LABELS[eventType]) return EVENT_LABELS[eventType]
  return eventType.replace(/[._]/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase())
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
