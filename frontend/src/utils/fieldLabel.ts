// Human field labels + help for node config.
//
// The backend pydantic schemas use engineering field names (companies_key,
// items_key, company_field, people_key). Rendered raw, they're cryptic to a user
// building a campaign. This maps the confusing ones to a plain label + one-line
// help written from the USER's perspective ("what do I put here / what does this
// do"), and falls back to a smart humaniser for everything else so NO field ever
// shows raw snake_case.

interface FieldCopy {
  label: string
  help?: string
}

// Curated copy for the fields users actually touch. Keyed by the raw field name.
// Help text answers "what is this, in plain words" — no jargon, no key-speak.
const FIELD_COPY: Record<string, FieldCopy> = {
  // ── source: company / people discovery ──────────────────────────────────
  companies_key: { label: 'Save companies as', help: 'Where to store the companies this finds, so the next step can use them. Leave as is unless you have two sources feeding different lists.' },
  people_key: { label: 'Save people as', help: 'Where to store the people this finds, so the next step can use them. Leave as is unless you know you need a different name.' },
  company_field: { label: 'Read company from', help: 'Which incoming item to look up people for. Leave as “item” — that’s what the loop before this passes in.' },
  company_name_field: { label: 'Company name field', help: 'The field on the incoming item that holds the company’s name. Usually “company_name”.' },
  query: { label: 'Search', help: 'What to search for — e.g. “fintech companies in London” or “B2B SaaS startups”.' },
  keyword: { label: 'Job keyword', help: 'A role to search hiring companies for — e.g. “software engineer”, “sales development rep”.' },
  location: { label: 'Location', help: 'Optional. Restrict results to a place — e.g. “Bangalore”, “Remote”.' },
  titles: { label: 'Roles to find', help: 'The job titles of the decision-makers to look for at each company — e.g. CEO, Founder, Head of Marketing.' },
  max_results: { label: 'Max results', help: 'How many companies to pull this run.' },
  max_companies: { label: 'Max companies', help: 'How many hiring companies to pull this run.' },
  max_per_company: { label: 'People per company', help: 'How many people to find at each company.' },
  min_results: { label: 'Minimum results', help: 'Skip the run if fewer than this many are found.' },
  max_pages: { label: 'Pages to scan', help: 'How many pages of results to read (more pages = more companies, slower).' },
  directory_url: { label: 'Directory page URL', help: 'The directory listing page to pull companies from (e.g. a Clutch category page).' },
  searxng_url: { label: 'Search server URL', help: 'Advanced. Override the search backend; leave blank to use the default.' },

  // ── flow ────────────────────────────────────────────────────────────────
  items_key: { label: 'List to loop over', help: 'The list this step walks through one by one — e.g. “companies” from a source, or “people” from a people search.' },
  item_key: { label: 'Name each item', help: 'What each item is called inside the loop. Leave as “item”; downstream steps expect that.' },
  max_items: { label: 'Loop limit', help: 'Safety cap on how many items the loop spawns per run.' },
  delay_seconds: { label: 'Wait (seconds)', help: 'How long to pause before continuing.' },
  earliest_hour: { label: 'Send after (hour)', help: 'Earliest hour of the day to send, in the campaign’s timezone (0–23).' },
  latest_hour: { label: 'Send before (hour)', help: 'Latest hour of the day to send, in the campaign’s timezone (1–24).' },
  days_of_week: { label: 'Send on days', help: 'Which weekdays to send on.' },

  // ── crm ───────────────────────────────────────────────────────────────────
  person_field: { label: 'Read person from', help: 'Which incoming item to turn into a contact. Leave as “item” — that’s what the loop before this passes in.' },
  source: { label: 'Contact source label', help: 'A tag stored on each contact for where it came from — e.g. “LinkedIn campaign”.' },
  new_stage: { label: 'Move deal to stage', help: 'The pipeline stage to move the deal into.' },
  icp_description: { label: 'Ideal-customer description', help: 'Describe your ideal customer in plain words — the AI screens each lead against this.' },

  // ── channels / connections ─────────────────────────────────────────────────
  connection_name: { label: 'Send using account', help: 'Which connected account sends this (e.g. your LinkedIn or email connection).' },
  sending_account_id: { label: 'Specific sender seat', help: 'Optional. Pin one exact seat to send from instead of the campaign’s pool.' },
  account_pool: { label: 'Sender rotation', help: 'How to pick a sender when several are available: rotate the campaign pool, or use a single one.' },
  subject_template: { label: 'Email subject', help: 'The subject line. Use {{first_name}}, {{company}} etc. to personalise.' },
  body_template: { label: 'Message', help: 'The message body. Use {{first_name}}, {{company}} etc. to personalise.' },
  instruction: { label: 'AI instruction', help: 'Tell the AI what to write or do, in plain words.' },
}

// Suffixes that are implementation detail, not meaning, when we have to fall back.
const NOISE_SUFFIX = /_(key|field|id|template|url|name)$/

const ACRONYMS: Record<string, string> = {
  url: 'URL', api: 'API', icp: 'ICP', ai: 'AI', crm: 'CRM', dm: 'DM', sms: 'SMS', id: 'ID',
}

/** Smart fallback: companies_key → "Companies", max_per_company → "Max per company". */
function humanise(name: string): string {
  const stripped = name.replace(NOISE_SUFFIX, '') || name
  return stripped
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w, i) => {
      const lower = w.toLowerCase()
      if (ACRONYMS[lower]) return ACRONYMS[lower]
      return i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : lower
    })
    .join(' ')
}

/** The label to show for a config field. Prefers curated copy, then the schema's
 *  own title (if the backend set one), then the smart humaniser. */
export function fieldLabel(name: string, schemaTitle?: string): string {
  if (FIELD_COPY[name]) return FIELD_COPY[name].label
  if (schemaTitle && schemaTitle !== name) return schemaTitle
  return humanise(name)
}

/** Plain-English help for a field, if we have curated copy for it. The schema
 *  description is used as a fallback by the caller. */
export function fieldHelp(name: string): string | undefined {
  return FIELD_COPY[name]?.help
}
