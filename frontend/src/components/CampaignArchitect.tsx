import { useMemo, useState } from 'react'
import {
  ArrowRight, Building2, ChevronDown, ChevronUp, GitBranch, Mail, MessageCircle,
  Plus, Rocket, ShieldCheck, Sparkles, Target, Trash2, Users,
} from 'lucide-react'
import {
  canvas,
  type CampaignSourceProvider,
  type CampaignSpec,
  type CampaignTemplateInfo,
  type EnrichmentProvider,
  type MessageChannel,
  type ObjectiveMetric,
  type WorkflowDetail,
} from '../api/v2'
import Badge from './Badge'
import Button from './Button'
import Card from './Card'
import { useToast } from './Toast'

type AuthoringMode = 'architect' | 'classic'

interface DraftSource {
  provider: CampaignSourceProvider
  query: string
  keyword: string
  connection_name: string
  location: string
  max_results: string
}

interface DraftEnrichment {
  provider: EnrichmentProvider
  connection_name: string
}

interface DraftMessage {
  channel: MessageChannel
  subject_template: string
  body_template: string
  message_template: string
  delay_amount: string
  delay_unit: 'hours' | 'days'
}

interface ClassicDraft {
  metric: ObjectiveMetric
  target: string
  keywords: string
  location: string
  templateId: string | null
  maxIterations: string
  maxSpend: string
}

interface BuildIssue {
  severity: 'error' | 'warning'
  message: string
}

interface BuildResult {
  spec: CampaignSpec | null
  issues: BuildIssue[]
  sourceCount: number
  enrichmentCount: number
  messageCount: number
}

interface Props {
  templates: CampaignTemplateInfo[]
  onCreated: (detail: WorkflowDetail) => void
  onCancel: () => void
}

const DEFAULT_SOURCE: DraftSource = {
  provider: 'naukri',
  query: '',
  keyword: 'software developer',
  connection_name: '',
  location: 'India',
  max_results: '100',
}

const DEFAULT_MESSAGE: DraftMessage = {
  channel: 'email',
  subject_template: 'Quick question, {{contact.first_name}}',
  body_template: '<p>Hi {{contact.first_name}},</p><p>Worth a quick conversation?</p>',
  message_template: 'Hi {{contact.first_name}} — worth connecting?',
  delay_amount: '3',
  delay_unit: 'days',
}

const DEFAULT_CLASSIC: ClassicDraft = {
  metric: 'qualified_leads',
  target: '50',
  keywords: '',
  location: '',
  templateId: null,
  maxIterations: '5',
  maxSpend: '',
}

export default function CampaignArchitect({ templates, onCreated, onCancel }: Props) {
  const toast = useToast()
  const [mode, setMode] = useState<AuthoringMode>('architect')
  const [name, setName] = useState('500 real contacts from stacked sources')
  const [targetContacts, setTargetContacts] = useState('500')
  const [audience, setAudience] = useState('software development companies')
  const [titles, setTitles] = useState('Founder, CEO, CTO')
  const [sources, setSources] = useState<DraftSource[]>([
    DEFAULT_SOURCE,
    {
      provider: 'searxng',
      query: 'site:clutch.co software development company',
      keyword: '',
      connection_name: '',
      location: '',
      max_results: '50',
    },
  ])
  const [peopleProvider, setPeopleProvider] = useState<'searxng_people' | 'serper_people'>('searxng_people')
  const [peopleConnection, setPeopleConnection] = useState('')
  const [maxPerCompany, setMaxPerCompany] = useState('4')
  const [enrichment, setEnrichment] = useState<DraftEnrichment[]>([
    { provider: 'proxycurl', connection_name: '' },
    { provider: 'hunter', connection_name: '' },
  ])
  const [messages, setMessages] = useState<DraftMessage[]>([
    DEFAULT_MESSAGE,
    { ...DEFAULT_MESSAGE, subject_template: 'Following up', body_template: '<p>Still worth exploring?</p>' },
  ])
  const [verificationThreshold, setVerificationThreshold] = useState('40')
  const [maxIterations, setMaxIterations] = useState('5')
  const [maxSpend, setMaxSpend] = useState('')
  const [classic, setClassic] = useState<ClassicDraft>(DEFAULT_CLASSIC)

  const buildResult = useMemo(() => buildSpec({
    name,
    targetContacts,
    audience,
    titles,
    sources,
    peopleProvider,
    peopleConnection,
    maxPerCompany,
    enrichment,
    messages,
    verificationThreshold,
    maxIterations,
    maxSpend,
  }), [
    name, targetContacts, audience, titles, sources, peopleProvider, peopleConnection,
    maxPerCompany, enrichment, messages, verificationThreshold, maxIterations, maxSpend,
  ])

  const createArchitect = async () => {
    if (!buildResult.spec) {
      toast.error(buildResult.issues.find((issue) => issue.severity === 'error')?.message ?? 'Complete the campaign architecture before creating it.')
      return
    }
    try {
      onCreated(await canvas.createFromSpec(buildResult.spec))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not create campaign')
    }
  }

  const createClassic = async () => {
    const target = Number(classic.target)
    if (!name.trim() || !Number.isInteger(target) || target <= 0) {
      toast.error('Name the campaign and set a positive target.')
      return
    }
    try {
      onCreated(await canvas.createFromGoal({
        name: name.trim(),
        metric: classic.metric,
        target,
        audience: {
          ...(classic.keywords.trim() ? { keywords: splitList(classic.keywords) } : {}),
          ...(classic.location.trim() ? { location: classic.location.trim() } : {}),
        },
        bounds: {
          max_iterations: Number(classic.maxIterations) || 5,
          ...(Number(classic.maxSpend) > 0 ? { max_spend_usd: Number(classic.maxSpend) } : {}),
        },
        template_id: classic.templateId,
      }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not create campaign')
    }
  }

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="border-b border-slate-100 bg-gradient-to-br from-slate-950 via-slate-900 to-brand-950 px-6 py-6 text-white dark:border-slate-800">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-brand-200">Campaign Architect</p>
            <h2 className="mt-2 text-2xl font-black tracking-tight">Design the outcome system, then let Omni compile the canvas.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300">
              Model the campaign as goals, incentives, source stacks, enrichment requirements, message sequences, and safety rules.
              The result is still a normal editable graph — this is the intuitive layer above it.
            </p>
          </div>
          <div className="grid gap-2 rounded-2xl border border-white/10 bg-white/5 p-3 text-xs text-slate-200 sm:grid-cols-3 lg:w-[420px]">
            <SummaryStat label="Sources" value={String(sources.length)} />
            <SummaryStat label="Enrichment" value={String(enrichment.length)} />
            <SummaryStat label="Messages" value={String(messages.length)} />
          </div>
        </div>
      </div>

      <div className="grid min-h-[640px] lg:grid-cols-[250px_1fr]">
        <aside className="border-b border-slate-100 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/50 lg:border-b-0 lg:border-r">
          <div className="space-y-2">
            <ModeButton active={mode === 'architect'} icon={Sparkles} title="Architect" body="Outcome + source/enrichment/message system" onClick={() => setMode('architect')} />
            <ModeButton active={mode === 'classic'} icon={GitBranch} title="Classic" body="Keep the existing goal/template workflow" onClick={() => setMode('classic')} />
          </div>
          <div className="mt-5 rounded-2xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-950/40">
            <p className="text-xs font-semibold text-slate-800 dark:text-slate-100">Compiled artifact</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              Every architect campaign becomes ordinary workflow nodes and edges, so power users can still tune the canvas.
            </p>
          </div>
        </aside>

        <main className="space-y-5 p-5">
          <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
            Campaign name
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900"
            />
          </label>

          {mode === 'architect' ? (
            <>
              <ArchitectSection icon={Target} title="1. Goal / incentive system" subtitle="Tell Omni what it is optimizing for and what counts as real progress.">
                <div className="grid gap-3 md:grid-cols-[160px_1fr_180px]">
                  <Field label="Real contacts">
                    <input type="number" min={1} value={targetContacts} onChange={(event) => setTargetContacts(event.target.value)} className={inputClass} />
                  </Field>
                  <Field label="Audience / market">
                    <input value={audience} onChange={(event) => setAudience(event.target.value)} placeholder="software development companies" className={inputClass} />
                  </Field>
                  <Field label="Buyer titles">
                    <input value={titles} onChange={(event) => setTitles(event.target.value)} placeholder="Founder, CEO" className={inputClass} />
                  </Field>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={Building2} title="2. Source stack" subtitle="Multiple sources start together. Each source can discover companies, then the shared pipeline enriches and dedupes them.">
                <div className="space-y-3">
                  {sources.map((source, index) => (
                    <SourceRow
                      key={index}
                      index={index}
                      source={source}
                      onChange={(next) => setSources((current) => replaceAt(current, index, next))}
                      onRemove={() => setSources((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    />
                  ))}
                  <Button variant="secondary" size="sm" icon={Plus} onClick={() => setSources((current) => [...current, { ...DEFAULT_SOURCE, keyword: audience || DEFAULT_SOURCE.keyword }])}>
                    Add source
                  </Button>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={Users} title="3. People discovery" subtitle="After companies are found and resolved, choose how Omni finds the right humans at each account.">
                <div className="grid gap-3 md:grid-cols-3">
                  <Field label="People source">
                    <select value={peopleProvider} onChange={(event) => setPeopleProvider(event.target.value as 'searxng_people' | 'serper_people')} className={inputClass}>
                      <option value="searxng_people">SearXNG people</option>
                      <option value="serper_people">Serper people</option>
                    </select>
                  </Field>
                  <Field label="Connection">
                    <input value={peopleConnection} onChange={(event) => setPeopleConnection(event.target.value)} placeholder="Required for Serper" className={inputClass} />
                  </Field>
                  <Field label="People per company">
                    <input type="number" min={1} value={maxPerCompany} onChange={(event) => setMaxPerCompany(event.target.value)} className={inputClass} />
                  </Field>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={Sparkles} title="4. Enrichment stack" subtitle="Stack data providers. Earlier stages win; later stages fill missing fields.">
                <div className="space-y-2">
                  {enrichment.map((stage, index) => (
                    <EnrichmentRow
                      key={index}
                      index={index}
                      stage={stage}
                      onChange={(next) => setEnrichment((current) => replaceAt(current, index, next))}
                      onRemove={() => setEnrichment((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    />
                  ))}
                  <Button variant="secondary" size="sm" icon={Plus} onClick={() => setEnrichment((current) => [...current, { provider: 'proxycurl', connection_name: '' }])}>
                    Add enrichment source
                  </Button>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={MessageCircle} title="5. Outreach sequence" subtitle="Create templated messages and automated follow-ups. Each step stops when the contact replies.">
                <div className="space-y-3">
                  {messages.map((message, index) => (
                    <MessageRow
                      key={index}
                      index={index}
                      message={message}
                      onChange={(next) => setMessages((current) => replaceAt(current, index, next))}
                      onRemove={() => setMessages((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    />
                  ))}
                  <Button variant="secondary" size="sm" icon={Plus} onClick={() => setMessages((current) => [...current, { ...DEFAULT_MESSAGE }])}>
                    Add message
                  </Button>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={ShieldCheck} title="6. Safety and precision" subtitle="Bounds keep autonomous pursuit controlled while the objective worker keeps chasing the target.">
                <div className="grid gap-3 md:grid-cols-3">
                  <Field label="Verification threshold">
                    <input type="number" min={0} max={100} value={verificationThreshold} onChange={(event) => setVerificationThreshold(event.target.value)} className={inputClass} />
                  </Field>
                  <Field label="Max pursuit iterations">
                    <input type="number" min={1} value={maxIterations} onChange={(event) => setMaxIterations(event.target.value)} className={inputClass} />
                  </Field>
                  <Field label="Max spend USD">
                    <input type="number" min={0} step="0.5" value={maxSpend} onChange={(event) => setMaxSpend(event.target.value)} placeholder="No cap" className={inputClass} />
                  </Field>
                </div>
              </ArchitectSection>

              <ReviewPanel result={buildResult} />
            </>
          ) : (
            <ClassicGoalForm
              templates={templates}
              draft={classic}
              onChange={setClassic}
            />
          )}

          <div className="sticky bottom-0 -mx-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 bg-white/95 px-5 py-4 backdrop-blur dark:border-slate-800 dark:bg-slate-950/95">
            <p className="text-xs text-slate-500">
              {mode === 'architect'
                ? 'Create the system, then inspect or tune the generated canvas.'
                : 'Classic mode preserves the existing goal/template creation flow.'}
            </p>
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={onCancel}>Cancel</Button>
              <Button variant="primary" icon={mode === 'architect' ? Sparkles : Target} onClick={mode === 'architect' ? createArchitect : createClassic}>
                {mode === 'architect' ? 'Create architected campaign' : 'Create classic campaign'}
              </Button>
            </div>
          </div>
        </main>
      </div>
    </Card>
  )
}

function buildSpec(input: {
  name: string
  targetContacts: string
  audience: string
  titles: string
  sources: DraftSource[]
  peopleProvider: 'searxng_people' | 'serper_people'
  peopleConnection: string
  maxPerCompany: string
  enrichment: DraftEnrichment[]
  messages: DraftMessage[]
  verificationThreshold: string
  maxIterations: string
  maxSpend: string
}): BuildResult {
  const issues: BuildIssue[] = []
  const target = Number(input.targetContacts)
  if (!input.name.trim()) issues.push({ severity: 'error', message: 'Campaign name is required.' })
  if (!Number.isInteger(target) || target <= 0) issues.push({ severity: 'error', message: 'Real contacts must be a positive whole number.' })
  const titles = splitList(input.titles)
  if (titles.length === 0) issues.push({ severity: 'error', message: 'Add at least one buyer title.' })
  const sources = input.sources.map((source, index) => {
    const sourceNumber = index + 1
    const query = source.provider === 'naukri' ? undefined : source.query.trim()
    const keyword = source.provider === 'naukri' ? source.keyword.trim() : undefined
    const connectionName = source.connection_name.trim() || undefined
    const maxResults = Number(source.max_results) || 25
    if (source.provider === 'naukri' && !keyword) issues.push({ severity: 'error', message: `Source ${sourceNumber} (Naukri) requires a role keyword.` })
    if (source.provider === 'searxng' && !query) issues.push({ severity: 'error', message: `Source ${sourceNumber} (SearXNG) requires a search query.` })
    if (source.provider === 'serper_search') {
      if (!query) issues.push({ severity: 'error', message: `Source ${sourceNumber} (Serper) requires a search query.` })
      if (!connectionName) issues.push({ severity: 'error', message: `Source ${sourceNumber} (Serper) requires a connection name.` })
    }
    if (!Number.isFinite(maxResults) || maxResults <= 0) issues.push({ severity: 'error', message: `Source ${sourceNumber} max results must be positive.` })
    return {
      provider: source.provider,
      query,
      keyword,
      connection_name: connectionName,
      location: source.location.trim() || undefined,
      max_results: maxResults,
      titles,
    }
  })
  if (sources.length === 0) issues.push({ severity: 'error', message: 'Add at least one source.' })
  if (input.peopleProvider === 'serper_people' && !input.peopleConnection.trim()) {
    issues.push({ severity: 'error', message: 'Serper people discovery requires a connection name.' })
  }
  const enrichment = input.enrichment.map((stage, index) => {
    const connectionName = stage.connection_name.trim()
    if (!connectionName) issues.push({ severity: 'error', message: `Enrichment stage ${index + 1} (${providerLabel(stage.provider)}) requires a connection name.` })
    return { provider: stage.provider, connection_name: connectionName }
  })
  const messages = input.messages.map((message, index) => {
    const messageNumber = index + 1
    if (message.channel === 'email') {
      if (!message.subject_template.trim()) issues.push({ severity: 'error', message: `Message ${messageNumber} email subject is required.` })
      if (!message.body_template.trim()) issues.push({ severity: 'error', message: `Message ${messageNumber} email body is required.` })
    }
    if (message.channel === 'linkedin' && !message.message_template.trim()) {
      issues.push({ severity: 'error', message: `Message ${messageNumber} LinkedIn text is required.` })
    }
    return {
      channel: message.channel,
      subject_template: message.channel === 'email' ? message.subject_template : undefined,
      body_template: message.channel === 'email' ? message.body_template : undefined,
      message_template: message.channel === 'linkedin' ? message.message_template : undefined,
      mode: message.channel === 'linkedin' ? ('dm' as const) : undefined,
      connection_name: undefined,
      delay_after: {
        amount: Number(message.delay_amount) || 3,
        unit: message.delay_unit,
      },
    }
  })
  if (issues.some((issue) => issue.severity === 'error')) {
    return {
      spec: null,
      issues,
      sourceCount: input.sources.length,
      enrichmentCount: input.enrichment.length,
      messageCount: input.messages.length,
    }
  }
  return {
    spec: {
      name: input.name.trim(),
      target_contacts: target,
      audience: {
        ...(input.audience.trim() ? { keywords: [input.audience.trim()] } : {}),
        titles,
      },
      bounds: {
        max_iterations: Number(input.maxIterations) || 5,
        ...(Number(input.maxSpend) > 0 ? { max_spend_usd: Number(input.maxSpend) } : {}),
      },
      sources,
      people: {
        provider: input.peopleProvider,
        connection_name: input.peopleConnection.trim() || undefined,
        titles,
        max_per_company: Number(input.maxPerCompany) || 4,
      },
      enrichment,
      messages,
      verification_threshold: Number(input.verificationThreshold) || 40,
    },
    issues,
    sourceCount: sources.length,
    enrichmentCount: enrichment.length,
    messageCount: messages.length,
  }
}

function splitList(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean)
}

function providerLabel(provider: EnrichmentProvider): string {
  return {
    apollo: 'Apollo',
    hunter: 'Hunter',
    proxycurl: 'Proxycurl',
  }[provider]
}

function replaceAt<T>(items: T[], index: number, next: T): T[] {
  return items.map((item, itemIndex) => (itemIndex === index ? next : item))
}

const inputClass = 'mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900'

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-slate-400">{label}</p>
      <p className="mt-0.5 text-lg font-black text-white">{value}</p>
    </div>
  )
}

function ModeButton({ active, icon: Icon, title, body, onClick }: { active: boolean; icon: typeof Sparkles; title: string; body: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className={`w-full rounded-2xl border p-3 text-left transition-colors ${active ? 'border-brand-300 bg-white shadow-sm dark:border-brand-800 dark:bg-slate-950' : 'border-transparent hover:border-slate-200 dark:hover:border-slate-800'}`}>
      <Icon size={16} className={active ? 'text-brand-500' : 'text-slate-400'} />
      <span className="mt-2 block text-sm font-bold text-slate-900 dark:text-white">{title}</span>
      <span className="mt-0.5 block text-xs leading-relaxed text-slate-500">{body}</span>
    </button>
  )
}

function ArchitectSection({ icon: Icon, title, subtitle, children }: { icon: typeof Target; title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-slate-200 p-4 dark:border-slate-800">
      <div className="mb-4 flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950/40">
          <Icon size={17} />
        </span>
        <div>
          <h3 className="text-sm font-bold text-slate-900 dark:text-white">{title}</h3>
          <p className="mt-0.5 text-xs leading-relaxed text-slate-500">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300">
      {label}
      {children}
    </label>
  )
}

function SourceRow({ index, source, onChange, onRemove }: { index: number; source: DraftSource; onChange: (source: DraftSource) => void; onRemove: () => void }) {
  return (
    <div className="grid gap-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800 md:grid-cols-[120px_1fr_130px_40px]">
      <Field label={`Source ${index + 1}`}>
        <select value={source.provider} onChange={(event) => onChange({ ...source, provider: event.target.value as CampaignSourceProvider })} className={inputClass}>
          <option value="naukri">Naukri companies</option>
          <option value="searxng">SearXNG companies</option>
          <option value="serper_search">Serper companies</option>
        </select>
      </Field>
      <Field label={source.provider === 'naukri' ? 'Role keyword' : 'Search query'}>
        <input value={source.provider === 'naukri' ? source.keyword : source.query} onChange={(event) => onChange(source.provider === 'naukri' ? { ...source, keyword: event.target.value } : { ...source, query: event.target.value })} className={inputClass} />
      </Field>
      <Field label="Max results">
        <input type="number" min={1} value={source.max_results} onChange={(event) => onChange({ ...source, max_results: event.target.value })} className={inputClass} />
      </Field>
      <button type="button" onClick={onRemove} className="mt-6 rounded-lg p-2 text-slate-300 hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-950/30" aria-label={`Remove source ${index + 1}`}>
        <Trash2 size={16} />
      </button>
      {source.provider === 'serper_search' && (
        <div className="md:col-span-4">
          <Field label="Serper connection name">
            <input value={source.connection_name} onChange={(event) => onChange({ ...source, connection_name: event.target.value })} placeholder="serper-prod" className={inputClass} />
          </Field>
        </div>
      )}
    </div>
  )
}

function EnrichmentRow({ index, stage, onChange, onRemove }: { index: number; stage: DraftEnrichment; onChange: (stage: DraftEnrichment) => void; onRemove: () => void }) {
  return (
    <div className="grid gap-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800 md:grid-cols-[180px_1fr_40px]">
      <Field label={`Stage ${index + 1}`}>
        <select value={stage.provider} onChange={(event) => onChange({ ...stage, provider: event.target.value as EnrichmentProvider })} className={inputClass}>
          <option value="proxycurl">Proxycurl</option>
          <option value="hunter">Hunter</option>
          <option value="apollo">Apollo</option>
        </select>
      </Field>
      <Field label="Connection name">
        <input value={stage.connection_name} onChange={(event) => onChange({ ...stage, connection_name: event.target.value })} placeholder={`${stage.provider}-prod`} className={inputClass} />
      </Field>
      <button type="button" onClick={onRemove} className="mt-6 rounded-lg p-2 text-slate-300 hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-950/30" aria-label={`Remove enrichment ${index + 1}`}>
        <Trash2 size={16} />
      </button>
    </div>
  )
}

function MessageRow({ index, message, onChange, onRemove }: { index: number; message: DraftMessage; onChange: (message: DraftMessage) => void; onRemove: () => void }) {
  return (
    <div className="space-y-3 rounded-xl border border-slate-100 p-3 dark:border-slate-800">
      <div className="grid gap-3 md:grid-cols-[150px_1fr_130px_40px]">
        <Field label={`Message ${index + 1}`}>
          <select value={message.channel} onChange={(event) => onChange({ ...message, channel: event.target.value as MessageChannel })} className={inputClass}>
            <option value="email">Email</option>
            <option value="linkedin">LinkedIn DM</option>
          </select>
        </Field>
        {message.channel === 'email' ? (
          <Field label="Subject">
            <input value={message.subject_template} onChange={(event) => onChange({ ...message, subject_template: event.target.value })} className={inputClass} />
          </Field>
        ) : (
          <Field label="LinkedIn message">
            <input value={message.message_template} onChange={(event) => onChange({ ...message, message_template: event.target.value })} className={inputClass} />
          </Field>
        )}
        <Field label="Wait after">
          <div className="mt-1 flex gap-1">
            <input type="number" min={1} value={message.delay_amount} onChange={(event) => onChange({ ...message, delay_amount: event.target.value })} className="w-16 rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm dark:border-slate-700 dark:bg-slate-900" />
            <select value={message.delay_unit} onChange={(event) => onChange({ ...message, delay_unit: event.target.value as 'hours' | 'days' })} className="flex-1 rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm dark:border-slate-700 dark:bg-slate-900">
              <option value="hours">hours</option>
              <option value="days">days</option>
            </select>
          </div>
        </Field>
        <button type="button" onClick={onRemove} className="mt-6 rounded-lg p-2 text-slate-300 hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-950/30" aria-label={`Remove message ${index + 1}`}>
          <Trash2 size={16} />
        </button>
      </div>
      {message.channel === 'email' && (
        <Field label="Email body">
          <textarea value={message.body_template} onChange={(event) => onChange({ ...message, body_template: event.target.value })} rows={3} className={`${inputClass} font-mono text-xs`} />
        </Field>
      )}
    </div>
  )
}

function ReviewPanel({ result }: { result: BuildResult }) {
  if (!result.spec) {
    return (
      <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-200">
        <p className="font-bold">Finish the required fields to compile this exact campaign system.</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          {result.issues.map((issue, index) => (
            <li key={index}>{issue.message}</li>
          ))}
        </ul>
      </div>
    )
  }
  const spec = result.spec
  return (
    <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/60 dark:bg-emerald-950/20">
      <div className="flex items-center gap-2 text-sm font-bold text-emerald-900 dark:text-emerald-200">
        <ArrowRight size={16} /> Ready to compile into canvas
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge label={`${spec.target_contacts} contacts`} variant="success" size="sm" />
        <Badge label={`${spec.sources.length} sources`} variant="success" size="sm" />
        <Badge label={`${spec.enrichment?.length ?? 0} enrichers`} variant="success" size="sm" />
        <Badge label={`${spec.messages?.length ?? 0} messages`} variant="success" size="sm" />
      </div>
    </div>
  )
}

function ClassicGoalForm({ templates, draft, onChange }: { templates: CampaignTemplateInfo[]; draft: ClassicDraft; onChange: (draft: ClassicDraft) => void }) {
  const [showBounds, setShowBounds] = useState(false)
  return (
    <div className="space-y-5">
      <ArchitectSection icon={Target} title="Classic goal creation" subtitle="The previous flow remains available: create a goal and optionally start from a template.">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {([
            { value: 'companies', label: 'Find companies', icon: Building2 },
            { value: 'contacts', label: 'Create contacts', icon: Users },
            { value: 'qualified_leads', label: 'Qualify leads', icon: ShieldCheck },
            { value: 'replies', label: 'Earn replies', icon: MessageCircle },
          ] as const).map((option) => {
            const Icon = option.icon
            return (
              <button key={option.value} type="button" onClick={() => onChange({ ...draft, metric: option.value })} className={`rounded-xl border p-3 text-left ${draft.metric === option.value ? 'border-brand-400 bg-brand-50 dark:bg-brand-950/30' : 'border-slate-200 dark:border-slate-700'}`}>
                <Icon size={16} className="text-brand-500" />
                <span className="mt-2 block text-sm font-semibold text-slate-900 dark:text-white">{option.label}</span>
              </button>
            )
          })}
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-[140px_1fr_180px]">
          <Field label="Target">
            <input type="number" min={1} value={draft.target} onChange={(event) => onChange({ ...draft, target: event.target.value })} className={inputClass} />
          </Field>
          <Field label="Keywords">
            <input value={draft.keywords} onChange={(event) => onChange({ ...draft, keywords: event.target.value })} placeholder="B2B SaaS, VP Marketing" className={inputClass} />
          </Field>
          <Field label="Location">
            <input value={draft.location} onChange={(event) => onChange({ ...draft, location: event.target.value })} placeholder="India or global" className={inputClass} />
          </Field>
        </div>
      </ArchitectSection>

      <ArchitectSection icon={Rocket} title="Starting plan" subtitle="Choose a starter graph or design directly on the canvas.">
        <div className="grid gap-2 md:grid-cols-2">
          <button type="button" onClick={() => onChange({ ...draft, templateId: null })} className={`rounded-xl border p-3 text-left ${draft.templateId === null ? 'border-brand-400 bg-brand-50 dark:bg-brand-950/30' : 'border-slate-200 dark:border-slate-700'}`}>
            <GitBranch size={16} className="text-brand-500" />
            <span className="mt-1.5 block text-sm font-semibold text-slate-900 dark:text-white">Design the plan</span>
            <span className="block text-xs text-slate-500">Clean canvas with the goal attached.</span>
          </button>
          {templates.map((template) => (
            <button key={template.id} type="button" onClick={() => onChange({ ...draft, templateId: template.id })} className={`rounded-xl border p-3 text-left ${draft.templateId === template.id ? 'border-brand-400 bg-brand-50 dark:bg-brand-950/30' : 'border-slate-200 dark:border-slate-700'}`}>
              <Rocket size={16} className="text-brand-500" />
              <span className="mt-1.5 block text-sm font-semibold text-slate-900 dark:text-white">{template.name}</span>
              <span className="block text-xs text-slate-500">{template.summary}</span>
            </button>
          ))}
        </div>
      </ArchitectSection>

      <div className="rounded-xl border border-slate-100 dark:border-slate-800">
        <button type="button" onClick={() => setShowBounds((value) => !value)} className="flex w-full items-center justify-between px-3 py-2.5 text-left">
          <span>
            <span className="block text-xs font-semibold text-slate-700 dark:text-slate-200">Safety bounds</span>
            <span className="block text-[11px] text-slate-400">Stop autonomous pursuit before it overspends or loops.</span>
          </span>
          {showBounds ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
        </button>
        {showBounds && (
          <div className="grid gap-3 border-t border-slate-100 p-3 sm:grid-cols-2 dark:border-slate-800">
            <Field label="Maximum attempts">
              <input type="number" min={1} value={draft.maxIterations} onChange={(event) => onChange({ ...draft, maxIterations: event.target.value })} className={inputClass} />
            </Field>
            <Field label="Maximum spend USD">
              <input type="number" min={0} step="0.5" value={draft.maxSpend} onChange={(event) => onChange({ ...draft, maxSpend: event.target.value })} placeholder="No cap" className={inputClass} />
            </Field>
          </div>
        )}
      </div>
    </div>
  )
}
