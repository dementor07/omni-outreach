import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRight, Building2, ChevronDown, ChevronUp, GitBranch, Mail, MessageCircle,
  Plus, Rocket, ShieldCheck, Sparkles, Target, Trash2, Users,
} from 'lucide-react'
import {
  canvas,
  type CampaignSourceProvider,
  type CampaignSpec,
  type CampaignTemplateInfo,
  type Connection,
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
  connections?: Connection[]
  onCreated: (detail: WorkflowDetail) => void
  onCancel: () => void
}


const ATS_PROVIDERS = new Set(['greenhouse', 'ashby', 'smartrecruiters', 'bamboohr', 'workday', 'icims', 'lever', 'workable', 'recruitee', 'personio', 'rippling', 'breezy'])
const NO_QUERY_PROVIDERS = new Set([...ATS_PROVIDERS, 'producthunt'])
const JOB_BOARD_PROVIDERS = new Set(['naukri', 'indeed', 'linkedin_jobs'])
const SEARCH_PROVIDERS = new Set(['searxng', 'serper_search', 'apollo', 'clutch'])

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

export default function CampaignArchitect({ templates, connections = [], onCreated, onCancel }: Props) {
  const toast = useToast()
  const [mode, setMode] = useState<AuthoringMode>('architect')
  const [name, setName] = useState('Connected-source contact campaign')
  const [targetContacts, setTargetContacts] = useState('25')
  const [audience, setAudience] = useState('software development companies')
  const [titles, setTitles] = useState('Founder, CEO, CTO')
  const [sources, setSources] = useState<DraftSource[]>([
    {
      provider: 'serper_search',
      query: 'site:clutch.co/profile "software development" India founder CEO CTO',
      keyword: '',
      connection_name: '',
      location: '',
      max_results: '20',
    },
    {
      provider: 'serper_search',
      query: 'site:clutch.co/profile "web development" India founder CEO CTO',
      keyword: '',
      connection_name: '',
      location: '',
      max_results: '20',
    },
  ])
  const [peopleProvider, setPeopleProvider] = useState<'searxng_people' | 'serper_people'>('serper_people')
  const [peopleConnection, setPeopleConnection] = useState('')
  const [maxPerCompany, setMaxPerCompany] = useState('4')
  const [enableScreening, setEnableScreening] = useState(false)
  const [screeningConnection, setScreeningConnection] = useState('')
  const [screeningPrompt, setScreeningPrompt] = useState('Looking for B2B SaaS companies.')
  const [enrichment, setEnrichment] = useState<DraftEnrichment[]>([])
  const [messages, setMessages] = useState<DraftMessage[]>([])
  const [verificationThreshold, setVerificationThreshold] = useState('40')
  const [maxIterations, setMaxIterations] = useState('5')
  const [maxSpend, setMaxSpend] = useState('')
  const [classic, setClassic] = useState<ClassicDraft>(DEFAULT_CLASSIC)
  const serperConnections = useMemo(() => connectionsForProvider(connections, 'serper'), [connections])
  const anthropicConnections = useMemo(() => connectionsForProvider(connections, 'anthropic'), [connections])
  const connectedEnrichmentProviders = useMemo(
    () => (['proxycurl', 'hunter', 'apollo'] as EnrichmentProvider[]).filter((provider) => connections.some((connection) => connection.provider === provider)),
    [connections],
  )

  useEffect(() => {
    const firstSerper = serperConnections[0]?.name
    if (!firstSerper) return
    setPeopleConnection((current) => current || firstSerper)
    setSources((current) => current.map((source) => (
      source.provider === 'serper_search' && !source.connection_name
        ? { ...source, connection_name: firstSerper }
        : source
    )))
  }, [serperConnections])

  useEffect(() => {
    const firstAnthropic = anthropicConnections[0]?.name
    if (!firstAnthropic) return
    setScreeningConnection((current) => current || firstAnthropic)
  }, [anthropicConnections])

  const buildResult = useMemo(() => buildSpec({
    name,
    targetContacts,
    audience,
    titles,
    sources,
    enableScreening,
    screeningConnection,
    screeningPrompt,
    peopleProvider,
    peopleConnection,
    maxPerCompany,
    enrichment,
    messages,
    verificationThreshold,
    maxIterations,
    maxSpend,
  }), [
    name, targetContacts, audience, titles, sources, enableScreening, screeningConnection, screeningPrompt, peopleProvider, peopleConnection,
    maxPerCompany, enrichment, messages, verificationThreshold, maxIterations, maxSpend,
  ])
  const architectReady = Boolean(buildResult.spec)

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
      <div className="relative overflow-hidden border-b border-slate-100 bg-gradient-to-br from-slate-950 via-slate-900 to-brand-950 px-6 py-8 text-white dark:border-slate-800">
        <div className="absolute -right-20 -top-20 h-64 w-64 rounded-full bg-brand-500/20 blur-3xl"></div>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[0.24em] text-brand-200">Goal campaign builder</p>
            <h2 className="mt-2 bg-gradient-to-r from-white to-slate-400 bg-clip-text text-2xl font-black tracking-tight text-transparent">Build a real multi-source campaign, then edit it on the canvas.</h2>
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-300">
              Stack company sources, pick the people-finding API, add connected enrichment only when it exists, and optionally add message templates.
              The result is still a normal editable graph.
            </p>
          </div>
          <div className="relative grid gap-2 rounded-2xl border border-white/10 bg-white/5 p-4 text-xs text-slate-200 shadow-xl backdrop-blur-md sm:grid-cols-3 lg:w-[420px]">
            <SummaryStat label="Sources" value={String(sources.length)} />
            <SummaryStat label="Enrichment" value={String(enrichment.length)} />
            <SummaryStat label="Messages" value={String(messages.length)} />
          </div>
        </div>
      </div>

      <div className="grid min-h-[640px] lg:grid-cols-[250px_1fr]">
        <aside className="border-b border-slate-100 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-900/50 lg:border-b-0 lg:border-r">
          <div className="space-y-2">
            <ModeButton active={mode === 'architect'} icon={Sparkles} title="Goal builder" body="Sources, people, verification, optional messages" onClick={() => setMode('architect')} />
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
              <ArchitectSection icon={Target} title="1. Goal" subtitle="Define exactly what counts as progress. Contacts mean verified people, not just company names.">
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

              <ArchitectSection icon={Building2} title="2. Company sources" subtitle="Run multiple sources together. Each source discovers companies; the shared pipeline resolves, dedupes, and verifies people.">
                <div className="space-y-3">
                  {sources.map((source, index) => (
                    <SourceRow
                      key={index}
                      index={index}
                      source={source}
                      connections={connections}
                      onChange={(next) => setSources((current) => replaceAt(current, index, next))}
                      onRemove={() => setSources((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    />
                  ))}
                  <Button variant="secondary" size="sm" icon={Plus} onClick={() => setSources((current) => [...current, { ...DEFAULT_SOURCE, keyword: audience || DEFAULT_SOURCE.keyword }])}>
                    Add source
                  </Button>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={ShieldCheck} title="Company validation" subtitle="Optionally screen companies using Claude before discovering people">
                <div className="rounded-xl border border-slate-100 p-4 dark:border-slate-800">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input 
                      type="checkbox" 
                      checked={enableScreening} 
                      onChange={(e) => setEnableScreening(e.target.checked)} 
                      className="rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                    />
                    <span className="text-sm font-bold text-slate-900 dark:text-white">Enable AI Company Screening</span>
                  </label>
                  
                  {enableScreening && (
                    <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_250px]">
                      <Field label="Screening Prompt">
                        <textarea
                          value={screeningPrompt}
                          onChange={(e) => setScreeningPrompt(e.target.value)}
                          rows={3}
                          placeholder="e.g., Only accept B2B SaaS companies. Reject agencies, e-commerce, and B2C."
                          className={inputClass}
                        />
                      </Field>
                      <Field label="Anthropic Connection">
                        {anthropicConnections.length > 0 ? (
                          <select value={screeningConnection} onChange={(e) => setScreeningConnection(e.target.value)} className={inputClass}>
                            <option value="">Choose connection</option>
                            {anthropicConnections.map((conn) => (
                              <option key={conn.id} value={conn.name}>{conn.name}</option>
                            ))}
                          </select>
                        ) : (
                          <p className="mt-1 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                            No Anthropic connection found. Add one in Integrations.
                          </p>
                        )}
                      </Field>
                    </div>
                  )}
                </div>
              </ArchitectSection>

              <ArchitectSection icon={Users} title="3. People discovery" subtitle="Choose how Omni finds the right humans at each company. Serper is selected by default because it is connected here.">
                <div className="grid gap-3 md:grid-cols-3">
                  <Field label="People source">
                    <select value={peopleProvider} onChange={(event) => setPeopleProvider(event.target.value as 'searxng_people' | 'serper_people')} className={inputClass}>
                      <option value="serper_people">Serper people</option>
                      <option value="searxng_people">SearXNG people</option>
                    </select>
                  </Field>
                  <Field label="Connection">
                    {peopleProvider === 'serper_people' && serperConnections.length > 0 ? (
                      <select value={peopleConnection} onChange={(event) => setPeopleConnection(event.target.value)} className={inputClass}>
                        <option value="">Choose connected Serper account</option>
                        {serperConnections.map((connection) => (
                          <option key={connection.id} value={connection.name}>{connection.name}</option>
                        ))}
                      </select>
                    ) : peopleProvider === 'serper_people' ? (
                      <p className="mt-1 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                        No connected Serper account found. Add Serper in Integrations before creating a connected API campaign.
                      </p>
                    ) : (
                      <p className="mt-1 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-900">
                        SearXNG people search uses the free self-hosted search service. No connection needed.
                      </p>
                    )}
                  </Field>
                  <Field label="People per company">
                    <input type="number" min={1} value={maxPerCompany} onChange={(event) => setMaxPerCompany(event.target.value)} className={inputClass} />
                  </Field>
                </div>
              </ArchitectSection>

              <ArchitectSection icon={Sparkles} title="4. Enrichment stack" subtitle="Only connected enrichment APIs are offered. Earlier stages win; later stages fill missing fields.">
                <div className="space-y-2">
                  {enrichment.map((stage, index) => (
                    <EnrichmentRow
                      key={index}
                      index={index}
                      stage={stage}
                      connections={connections}
                      onChange={(next) => setEnrichment((current) => replaceAt(current, index, next))}
                      onRemove={() => setEnrichment((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                    />
                  ))}
                  {connectedEnrichmentProviders.length > 0 ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={Plus}
                      onClick={() => {
                        const provider = connectedEnrichmentProviders.find((candidate) => !enrichment.some((stage) => stage.provider === candidate))
                        if (!provider) return
                        const connection = connections.find((item) => item.provider === provider)
                        setEnrichment((current) => [...current, { provider, connection_name: connection?.name ?? '' }])
                      }}
                    >
                      Add connected enrichment source
                    </Button>
                  ) : (
                    <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-500 dark:border-slate-800 dark:bg-slate-900/40">
                      No connected enrichment API is active in this workspace, so enrichment is left out of this campaign. Connect one in Integrations and it will appear here.
                    </div>
                  )}
                </div>
              </ArchitectSection>

              <ArchitectSection icon={MessageCircle} title="5. Message sequence (optional)" subtitle="Create templated messages and automated follow-ups only when you want the generated canvas to include sending nodes.">
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
                  {messages.length === 0 && (
                    <p className="rounded-xl bg-slate-50 px-3 py-2 text-xs text-slate-500 dark:bg-slate-900/40">
                      No messages will be created. This campaign will stop after verified contacts are created.
                    </p>
                  )}
                </div>
              </ArchitectSection>

              <ArchitectSection icon={ShieldCheck} title="6. Safety and precision" subtitle="Bounds keep repeated runs controlled while the objective worker keeps working toward the target.">
                <div className="grid gap-3 md:grid-cols-3">
                  <Field label="Verification threshold">
                    <input type="number" min={0} max={100} value={verificationThreshold} onChange={(event) => setVerificationThreshold(event.target.value)} className={inputClass} />
                  </Field>
                  <Field label="Max attempts">
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

          <div className="sticky bottom-0 -mx-5 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100/50 bg-white/80 px-5 py-5 backdrop-blur-xl dark:border-slate-800/50 dark:bg-slate-950/80">
            <p className="text-xs text-slate-500">
              {mode === 'architect'
                ? 'Create the campaign, then inspect or tune the generated canvas.'
                : 'Classic mode preserves the existing goal/template creation flow.'}
            </p>
            <div className="flex items-center gap-2">
              <Button variant="ghost" onClick={onCancel}>Cancel</Button>
              <Button
                variant="primary"
                icon={mode === 'architect' ? Sparkles : Target}
                onClick={mode === 'architect' ? createArchitect : createClassic}
                disabled={mode === 'architect' && !architectReady}
              >
                {mode === 'architect' ? 'Create campaign' : 'Create classic campaign'}
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
  enableScreening: boolean
  screeningConnection: string
  screeningPrompt: string
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
    const query = SEARCH_PROVIDERS.has(source.provider) ? source.query.trim() : (source.provider === 'producthunt' ? undefined : source.query.trim())
    const keyword = JOB_BOARD_PROVIDERS.has(source.provider) ? source.keyword.trim() : undefined
    const connectionName = source.connection_name.trim() || undefined
    const maxResults = Number(source.max_results) || 25
    if (JOB_BOARD_PROVIDERS.has(source.provider) && !keyword) issues.push({ severity: 'error', message: `Source ${sourceNumber} (${source.provider}) requires a role keyword.` })
    if (SEARCH_PROVIDERS.has(source.provider) && !query) issues.push({ severity: 'error', message: `Source ${sourceNumber} (${source.provider}) requires a search query.` })
    if (source.provider === 'serper_search') {
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
  if (input.enableScreening && !input.screeningConnection.trim()) {
    issues.push({ severity: 'error', message: 'Anthropic connection is required for AI Company Screening.' })
  }
  if (input.enableScreening && !input.screeningPrompt.trim()) {
    issues.push({ severity: 'error', message: 'A screening prompt is required for AI Company Screening.' })
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
      ...(input.enableScreening ? {
        company_screening: {
          connection_name: input.screeningConnection,
          prompt: input.screeningPrompt,
        }
      } : {}),
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

function connectionsForProvider(connections: Connection[], provider: string): Connection[] {
  return connections.filter((connection) => connection.provider === provider)
}

function replaceAt<T>(items: T[], index: number, next: T): T[] {
  return items.map((item, itemIndex) => (itemIndex === index ? next : item))
}

const inputClass = 'mt-1 w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm shadow-sm transition-all focus:border-brand-500 focus:outline-none focus:ring-4 focus:ring-brand-500/10 dark:border-slate-700/80 dark:bg-slate-900/50'

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
    <button type="button" onClick={onClick} className={`group w-full rounded-2xl border p-3 text-left transition-all duration-300 ${active ? 'border-brand-300 bg-white shadow-md dark:border-brand-800 dark:bg-slate-950/80 dark:shadow-brand-900/10' : 'border-transparent hover:scale-[1.02] hover:bg-white/50 dark:hover:bg-slate-900/30'}`}>
      <Icon size={16} className={`transition-transform duration-300 group-hover:scale-110 ${active ? 'text-brand-500' : 'text-slate-400'}`} />
      <span className="mt-2 block text-sm font-bold text-slate-900 dark:text-white">{title}</span>
      <span className="mt-0.5 block text-xs leading-relaxed text-slate-500">{body}</span>
    </button>
  )
}

function ArchitectSection({ icon: Icon, title, subtitle, children }: { icon: typeof Target; title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="group rounded-3xl border border-slate-200 bg-white/40 p-5 shadow-sm transition-shadow hover:shadow-md dark:border-slate-800/60 dark:bg-slate-900/20">
      <div className="mb-5 flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 transition-transform duration-500 group-hover:-rotate-6 group-hover:scale-110 dark:bg-brand-950/40">
          <Icon size={18} />
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

function SourceRow({
  index,
  source,
  connections,
  onChange,
  onRemove,
}: {
  index: number
  source: DraftSource
  connections: Connection[]
  onChange: (source: DraftSource) => void
  onRemove: () => void
}) {
  const serperConnections = connectionsForProvider(connections, 'serper')
  const isJobBoard = JOB_BOARD_PROVIDERS.has(source.provider)
  const isSearch = SEARCH_PROVIDERS.has(source.provider)
  const isATS = NO_QUERY_PROVIDERS.has(source.provider)
  
  return (
    <div className="group relative grid gap-3 rounded-2xl border border-slate-100 bg-white p-4 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/50 md:grid-cols-[160px_1fr_130px_40px]">
      <Field label={`Source ${index + 1}`}>
        <select
          value={source.provider}
          onChange={(event) => {
            const provider = event.target.value as CampaignSourceProvider
            onChange({
              ...source,
              provider,
              connection_name: provider === 'serper_search' ? (serperConnections[0]?.name ?? '') : '',
            })
          }}
          className={`${inputClass} font-medium text-slate-800 dark:text-slate-100`}
        >
          <optgroup label="Search & Directories">
            <option value="searxng">SearXNG</option>
            <option value="serper_search">Serper (Google)</option>
            <option value="apollo">Apollo.io</option>
            <option value="clutch">Clutch</option>
            <option value="producthunt">Product Hunt</option>
          </optgroup>
          <optgroup label="Job Boards">
            <option value="linkedin_jobs">LinkedIn Jobs</option>
            <option value="indeed">Indeed</option>
            <option value="naukri">Naukri</option>
          </optgroup>
          <optgroup label="ATS (Hiring Companies)">
            <option value="greenhouse">Greenhouse</option>
            <option value="ashby">Ashby</option>
            <option value="lever">Lever</option>
            <option value="workday">Workday</option>
            <option value="smartrecruiters">SmartRecruiters</option>
            <option value="bamboohr">BambooHR</option>
            <option value="icims">iCIMS</option>
            <option value="workable">Workable</option>
            <option value="recruitee">Recruitee</option>
            <option value="personio">Personio</option>
            <option value="rippling">Rippling</option>
            <option value="breezy">Breezy</option>
          </optgroup>
        </select>
      </Field>
      
      {isATS ? (
        <div className="flex items-center rounded-xl bg-slate-50 px-4 text-xs leading-relaxed text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
          This source pulls directly from a global index or feed. No keyword required.
        </div>
      ) : (
        <Field label={isJobBoard ? 'Role keyword' : 'Search query'}>
          <input 
            value={isJobBoard ? source.keyword : source.query} 
            onChange={(event) => onChange(isJobBoard ? { ...source, keyword: event.target.value } : { ...source, query: event.target.value })} 
            placeholder={isJobBoard ? 'e.g. Software Engineer' : 'e.g. B2B SaaS companies'}
            className={`${inputClass} transition-shadow focus:ring-2 focus:ring-brand-500/20`} 
          />
        </Field>
      )}

      <Field label="Max results">
        <input type="number" min={1} value={source.max_results} onChange={(event) => onChange({ ...source, max_results: event.target.value })} className={`${inputClass} transition-shadow focus:ring-2 focus:ring-brand-500/20`} />
      </Field>

      <button type="button" onClick={onRemove} className="mt-6 flex h-9 w-9 items-center justify-center rounded-xl text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-500 dark:text-slate-600 dark:hover:bg-rose-950/40 dark:hover:text-rose-400" aria-label={`Remove source ${index + 1}`}>
        <Trash2 size={16} />
      </button>

      {source.provider === 'serper_search' && (
        <div className="md:col-span-4 mt-2">
          <Field label="Serper connection name">
            {serperConnections.length > 0 ? (
              <select value={source.connection_name} onChange={(event) => onChange({ ...source, connection_name: event.target.value })} className={`${inputClass} max-w-sm`}>
                <option value="">Choose connected Serper account</option>
                {serperConnections.map((connection) => (
                  <option key={connection.id} value={connection.name}>{connection.name}</option>
                ))}
              </select>
            ) : (
              <p className="mt-1 rounded-xl bg-amber-50/50 px-4 py-3 text-xs font-medium text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
                No connected Serper account found. Add Serper in Integrations or remove this Serper source.
              </p>
            )}
          </Field>
        </div>
      )}
    </div>
  )
}

function EnrichmentRow({
  index,
  stage,
  connections,
  onChange,
  onRemove,
}: {
  index: number
  stage: DraftEnrichment
  connections: Connection[]
  onChange: (stage: DraftEnrichment) => void
  onRemove: () => void
}) {
  const providerConnections = connections.filter((connection) => connection.provider === stage.provider)
  const connectedProviders = (['proxycurl', 'hunter', 'apollo'] as EnrichmentProvider[]).filter(
    (provider) => connections.some((connection) => connection.provider === provider),
  )
  return (
    <div className="group relative grid gap-3 rounded-2xl border border-slate-100 bg-white p-4 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/50 md:grid-cols-[180px_1fr_40px]">
      <Field label={`Stage ${index + 1}`}>
        <select
          value={stage.provider}
          onChange={(event) => {
            const provider = event.target.value as EnrichmentProvider
            const firstConnection = connections.find((connection) => connection.provider === provider)
            onChange({ provider, connection_name: firstConnection?.name ?? '' })
          }}
          className={inputClass}
        >
          {connectedProviders.map((provider) => (
            <option key={provider} value={provider}>{providerLabel(provider)}</option>
          ))}
        </select>
      </Field>
      <Field label="Connection name">
        {providerConnections.length > 0 ? (
          <select value={stage.connection_name} onChange={(event) => onChange({ ...stage, connection_name: event.target.value })} className={inputClass}>
            <option value="">Choose connected {providerLabel(stage.provider)} account</option>
            {providerConnections.map((connection) => (
              <option key={connection.id} value={connection.name}>{connection.name}</option>
            ))}
          </select>
        ) : (
          <p className="mt-1 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
            {providerLabel(stage.provider)} is not connected. Remove this row or connect it in Integrations.
          </p>
        )}
      </Field>
      <button type="button" onClick={onRemove} className="mt-6 flex h-9 w-9 items-center justify-center rounded-xl text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-500 dark:text-slate-600 dark:hover:bg-rose-950/40 dark:hover:text-rose-400" aria-label={`Remove enrichment ${index + 1}`}>
        <Trash2 size={16} />
      </button>
    </div>
  )
}

function MessageRow({ index, message, onChange, onRemove }: { index: number; message: DraftMessage; onChange: (message: DraftMessage) => void; onRemove: () => void }) {
  return (
    <div className="group relative space-y-3 rounded-2xl border border-slate-100 bg-white p-4 shadow-sm transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/50">
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
        <button type="button" onClick={onRemove} className="mt-6 flex h-9 w-9 items-center justify-center rounded-xl text-slate-300 opacity-0 transition-all group-hover:opacity-100 hover:bg-rose-50 hover:text-rose-500 dark:text-slate-600 dark:hover:bg-rose-950/40 dark:hover:text-rose-400" aria-label={`Remove message ${index + 1}`}>
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
            <span className="block text-[11px] text-slate-400">Stop repeated attempts before they overspend or loop.</span>
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
