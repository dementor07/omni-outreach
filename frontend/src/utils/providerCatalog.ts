import {
  Mail, MessageSquare, Phone, Linkedin, Slack, Search, Target, Sparkles,
  Send, Instagram, MessageCircle, Globe, Database, FileSpreadsheet, Users,
  type LucideIcon,
} from 'lucide-react'

/* The provider catalog — the single source of truth for every external
 * integration Omni knows how to talk to. Nodes declare `connection:<id>`
 * capabilities; this catalog is the operator-facing mirror of that, so a
 * known provider (Apollo, SMTP, Twilio, …) is a first-class, named tile with
 * a TYPED credential form — not a free-text provider string the user has to
 * guess at and a raw JSON blob they hand-write.
 *
 * Keyed by the exact `provider` id stored in `omni_connections.provider`
 * (i.e. the suffix of the node's `connection:<id>` capability). */

export type ProviderCategory = 'ai' | 'email' | 'messaging' | 'voice' | 'data' | 'social'

export interface CredentialField {
  /** Key written into the credentials/metadata bundle. */
  key: string
  label: string
  /** `secret` masks input + lands in `credentials`; everything else lands in `metadata`. */
  type: 'secret' | 'text' | 'number'
  placeholder?: string
  /** Optional — falls back to required. */
  optional?: boolean
  /** Non-secret config (host, port, From address) → stored in `metadata`, not `credentials`. */
  metadata?: boolean
}

export interface ProviderSpec {
  id: string
  name: string
  category: ProviderCategory
  icon: LucideIcon
  /** One-line operator-facing description of what connecting this unlocks. */
  blurb: string
  /** Where to get the key, shown under the form. */
  docsUrl?: string
  /** The typed fields the connect form renders. Secrets → credentials, rest → metadata. */
  fields: CredentialField[]
  /** OAuth providers can't take a pasted key — they redirect. Marked so the UI can route them. */
  oauth?: boolean
}

const API_KEY: CredentialField = { key: 'api_key', label: 'API key', type: 'secret', placeholder: 'Paste your API key' }

export const PROVIDERS: ProviderSpec[] = [
  // ── AI providers ───────────────────────────────────────────────────────────
  {
    id: 'anthropic', name: 'Anthropic (Claude)', category: 'ai', icon: Sparkles,
    blurb: 'Powers ICP screening, lead scoring, AI compose, and reply classification.',
    docsUrl: 'https://console.anthropic.com/settings/keys',
    fields: [{ key: 'api_key', label: 'API key', type: 'secret', placeholder: 'sk-ant-…' }],
  },
  {
    id: 'openai', name: 'OpenAI', category: 'ai', icon: Sparkles,
    blurb: 'Alternative model provider for message composition and scoring.',
    docsUrl: 'https://platform.openai.com/api-keys',
    fields: [{ key: 'api_key', label: 'API key', type: 'secret', placeholder: 'sk-…' }],
  },
  {
    id: 'gemini', name: 'Google Gemini', category: 'ai', icon: Sparkles,
    blurb: 'Google model provider for AI composition workflows.',
    docsUrl: 'https://aistudio.google.com/apikey',
    fields: [API_KEY],
  },
  {
    id: 'mindstudio', name: 'MindStudio', category: 'ai', icon: Sparkles,
    blurb: 'Hosted AI workflows for message composition.',
    fields: [API_KEY],
  },

  // ── Email ────────────────────────────────────────────────────────────────
  {
    id: 'smtp', name: 'SMTP (email sending)', category: 'email', icon: Mail,
    blurb: 'Send campaign email through your own mail server.',
    fields: [
      { key: 'host', label: 'SMTP host', type: 'text', placeholder: 'smtp.yourdomain.com', metadata: true },
      { key: 'port', label: 'Port', type: 'number', placeholder: '587', metadata: true },
      { key: 'from_address', label: 'From address', type: 'text', placeholder: 'outreach@yourdomain.com', metadata: true },
      { key: 'username', label: 'Username', type: 'text', placeholder: 'SMTP username' },
      { key: 'password', label: 'Password', type: 'secret', placeholder: 'SMTP password' },
    ],
  },
  {
    id: 'zerobounce', name: 'ZeroBounce', category: 'email', icon: Mail,
    blurb: 'Mailbox verification stage with catch-all, abuse, spamtrap, and do-not-mail signals.',
    docsUrl: 'https://www.zerobounce.net/docs/email-validation-api-quickstart',
    fields: [
      API_KEY,
      { key: 'verification_priority', label: 'Waterfall priority', type: 'number', placeholder: '20', optional: true, metadata: true },
      { key: 'verification_timeout_seconds', label: 'Timeout seconds', type: 'number', placeholder: '12', optional: true, metadata: true },
    ],
  },

  // ── Messaging / social channels ──────────────────────────────────────────
  {
    id: 'twilio', name: 'Twilio (SMS)', category: 'messaging', icon: MessageSquare,
    blurb: 'Send SMS through Twilio.',
    docsUrl: 'https://console.twilio.com',
    fields: [
      { key: 'account_sid', label: 'Account SID', type: 'text', placeholder: 'AC…' },
      { key: 'auth_token', label: 'Auth token', type: 'secret' },
      { key: 'from_number', label: 'From number', type: 'text', placeholder: '+15551234567', metadata: true },
    ],
  },
  {
    id: 'unipile', name: 'LinkedIn (via Unipile)', category: 'social', icon: Linkedin,
    blurb: 'Send LinkedIn connection requests and messages through Unipile.',
    docsUrl: 'https://www.unipile.com',
    // The account-sync reads credentials.api_key + credentials.base_url
    // (integrations.py sync_accounts). The base_url must be the full Unipile DSN
    // URL incl. scheme + port, e.g. https://apiNN.unipile.com:NNNNN — that's what
    // GET {base_url}/api/v1/accounts needs. (Was 'dsn' stored as metadata, which
    // the sync never read → "invalid credentials" on every Unipile connect.)
    fields: [
      { key: 'api_key', label: 'API key', type: 'secret' },
      { key: 'base_url', label: 'DSN base URL', type: 'text', placeholder: 'https://api10.unipile.com:14090' },
    ],
  },
  {
    id: 'slack', name: 'Slack', category: 'messaging', icon: Slack,
    blurb: 'Post hot-lead alerts and notifications to a Slack channel.',
    docsUrl: 'https://api.slack.com/apps',
    fields: [
      { key: 'bot_token', label: 'Bot token', type: 'secret', placeholder: 'xoxb-…' },
      { key: 'default_channel', label: 'Default channel', type: 'text', placeholder: '#leads', optional: true, metadata: true },
    ],
  },
  {
    id: 'telegram', name: 'Telegram', category: 'messaging', icon: Send,
    blurb: 'Send Telegram messages via a bot.',
    fields: [{ key: 'bot_token', label: 'Bot token', type: 'secret' }],
  },
  {
    id: 'whatsapp', name: 'WhatsApp', category: 'messaging', icon: MessageCircle,
    blurb: 'Send WhatsApp messages.',
    fields: [
      { key: 'access_token', label: 'Access token', type: 'secret' },
      { key: 'phone_number_id', label: 'Phone number ID', type: 'text', metadata: true },
    ],
  },
  {
    id: 'instagram', name: 'Instagram', category: 'social', icon: Instagram,
    blurb: 'Send Instagram direct messages.',
    fields: [{ key: 'access_token', label: 'Access token', type: 'secret' }],
  },
  {
    id: 'retell', name: 'Retell (AI voice)', category: 'voice', icon: Phone,
    blurb: 'Place AI voice calls through Retell.',
    docsUrl: 'https://www.retellai.com',
    fields: [{ key: 'api_key', label: 'API key', type: 'secret' }],
  },

  // ── Data / lead sources ────────────────────────────────────────────────────
  {
    id: 'apollo', name: 'Apollo', category: 'data', icon: Target,
    blurb: 'Pull people and companies from Apollo as a lead source.',
    docsUrl: 'https://developer.apollo.io',
    fields: [API_KEY],
  },
  {
    id: 'serper', name: 'Serper (Google search)', category: 'data', icon: Search,
    blurb: 'Google-search-powered company and people discovery.',
    docsUrl: 'https://serper.dev',
    fields: [API_KEY],
  },
  {
    id: 'linkfinder', name: 'LinkFinder AI', category: 'data', icon: Users,
    blurb: 'AI lead finder and profile/company enrichment through LinkFinder.',
    docsUrl: 'https://linkfinderai.com/api-documentation',
    fields: [API_KEY],
  },
  {
    id: 'apify', name: 'Apify', category: 'data', icon: Globe,
    blurb: 'Run Apify actors for LinkedIn Jobs / Indeed scraping.',
    docsUrl: 'https://console.apify.com/account/integrations',
    fields: [{ key: 'api_token', label: 'API token', type: 'secret', placeholder: 'apify_api_…' }],
  },
  {
    id: 'hunter', name: 'Hunter.io', category: 'data', icon: Mail,
    blurb: 'Find professional emails and run a provider-backed verification stage.',
    docsUrl: 'https://hunter.io/api-keys',
    fields: [
      API_KEY,
      { key: 'verification_priority', label: 'Waterfall priority', type: 'number', placeholder: '10', optional: true, metadata: true },
      { key: 'verification_timeout_seconds', label: 'Timeout seconds', type: 'number', placeholder: '12', optional: true, metadata: true },
    ],
  },
  {
    id: 'proxycurl', name: 'Proxycurl', category: 'data', icon: Linkedin,
    blurb: 'Enrich LinkedIn profiles and companies.',
    fields: [API_KEY],
  },

  // ── OAuth (redirect, no pasted key) ──────────────────────────────────────────
  {
    id: 'sheets', name: 'Google Sheets', category: 'data', icon: FileSpreadsheet,
    blurb: 'Import leads from a Google Sheet.', oauth: true, fields: [],
  },
  {
    id: 'producthunt', name: 'Product Hunt', category: 'data', icon: Globe,
    blurb: 'Discover makers and companies from Product Hunt.', oauth: true, fields: [],
  },
]

const BY_ID: Record<string, ProviderSpec> = Object.fromEntries(PROVIDERS.map((p) => [p.id, p]))

/** Look up a known provider by its id; undefined for unknown/custom ids. */
export function providerSpec(id: string): ProviderSpec | undefined {
  return BY_ID[id]
}

/** Display name for a provider id — falls back to the raw id for unknown providers. */
export function providerName(id: string): string {
  return BY_ID[id]?.name ?? id
}

/** Icon for a provider id, with a safe default. */
export function providerIcon(id: string): LucideIcon {
  return BY_ID[id]?.icon ?? Database
}

export const CATEGORY_LABEL: Record<ProviderCategory, string> = {
  ai: 'AI providers',
  email: 'Email',
  messaging: 'Messaging',
  voice: 'Voice',
  data: 'Data & lead sources',
  social: 'Social channels',
}
