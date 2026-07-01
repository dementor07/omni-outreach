import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Plus, Save, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'
import type { Connection, NodeManifest } from '../api/v2'
import { categoryLabel, handleLabel, nodeLabel } from '../utils/nodeLabel'
import { fieldLabel, fieldHelp } from '../utils/fieldLabel'
import Button from './Button'
import Select from './Select'

/** A single field derived from a JSON-Schema property. */
interface SchemaField {
  name: string
  title: string
  description?: string
  type: 'string' | 'number' | 'integer' | 'boolean' | 'enum'
  format?: string
  enumValues?: string[]
  required: boolean
  default?: unknown
  isLong: boolean // render a textarea
}

interface JsonSchemaProp {
  title?: string
  description?: string
  type?: string
  format?: string
  default?: unknown
  enum?: string[]
  anyOf?: Array<{ type?: string; format?: string; enum?: string[] }>
  maxLength?: number
}

interface JsonSchema {
  properties?: Record<string, JsonSchemaProp>
  required?: string[]
}

interface ConditionRuleValue {
  field: string
  operator: string
  value?: unknown
}

const CONDITION_OPERATORS = [
  { value: 'equals', label: 'equals' },
  { value: 'not_equals', label: 'does not equal' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'does not contain' },
  { value: 'starts_with', label: 'starts with' },
  { value: 'ends_with', label: 'ends with' },
  { value: 'gt', label: 'is greater than' },
  { value: 'gte', label: 'is at least' },
  { value: 'lt', label: 'is less than' },
  { value: 'lte', label: 'is at most' },
  { value: 'one_of', label: 'is one of' },
  { value: 'not_one_of', label: 'is not one of' },
  { value: 'is_set', label: 'is set' },
  { value: 'is_not_set', label: 'is not set' },
  { value: 'is_true', label: 'is true' },
  { value: 'is_false', label: 'is false' },
  { value: 'regex', label: 'matches regular expression' },
]

const VALUELESS_OPERATORS = new Set(['is_set', 'is_not_set', 'is_true', 'is_false'])

const COMMON_FIELDS = [
  'email',
  'first_name',
  'last_name',
  'company',
  'headline',
  'phone',
  'linkedin_url',
  'custom_fields.title',
  'custom_fields.location',
  'custom_fields.industry',
  'custom_fields.employee_count',
  'custom_fields.icp_score',
  'custom_fields.verification_status',
]

/** Long-text heuristic: templates/prompts/descriptions render as textareas. */
const LONG_FIELD_HINTS = ['template', 'body', 'prompt', 'description', 'instruction', 'message', 'inputs_json', 'blocks_json']

function fieldsFromSchema(schema: JsonSchema): SchemaField[] {
  const props = schema.properties ?? {}
  const required = new Set(schema.required ?? [])
  return Object.entries(props).map(([name, prop]) => {
    // Resolve nullable (anyOf [T, null]) and enum shapes.
    const variant = prop.anyOf?.find((v) => v.type && v.type !== 'null') ?? prop
    const enumValues = prop.enum ?? variant.enum
    let type: SchemaField['type'] = 'string'
    if (enumValues) type = 'enum'
    else if (variant.type === 'integer') type = 'integer'
    else if (variant.type === 'number') type = 'number'
    else if (variant.type === 'boolean') type = 'boolean'
    const isLong =
      type === 'string' &&
      (LONG_FIELD_HINTS.some((h) => name.toLowerCase().includes(h)) || (prop.maxLength ?? 0) > 200)
    return {
      name,
      // Human label + plain-English help (overrides the raw snake_case name and
      // the often-terse schema description) — see utils/fieldLabel.
      title: fieldLabel(name, prop.title),
      description: fieldHelp(name) ?? prop.description,
      type,
      format: variant.format,
      enumValues,
      required: required.has(name),
      default: prop.default,
      isLong,
    }
  })
}

interface NodeConfigPanelProps {
  manifest: NodeManifest
  nodeId: string
  initialConfig: Record<string, unknown>
  saving: boolean
  connections?: Connection[]
  wiredOutputHandles?: string[]
  onSave: (config: Record<string, unknown>) => void
  onDelete?: () => void
  onClose: () => void
}

export default function NodeConfigPanel({
  manifest,
  nodeId,
  initialConfig,
  saving,
  connections = [],
  wiredOutputHandles = [],
  onSave,
  onDelete,
  onClose,
}: NodeConfigPanelProps) {
  const fields = useMemo(() => fieldsFromSchema(manifest.config_schema as JsonSchema), [manifest])
  const [values, setValues] = useState<Record<string, unknown>>(initialConfig)
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Reset the form when switching to a different node.
  useEffect(() => {
    setValues(initialConfig)
    setShowAdvanced(
      (manifest.advanced_fields ?? []).some((name) => !isEmpty(initialConfig[name])),
    )
  }, [nodeId, initialConfig, manifest.advanced_fields])

  function setField(name: string, value: unknown) {
    setValues((v) => ({ ...v, [name]: value }))
  }

  const preferred = new Set(manifest.primary_fields ?? [])
  const explicitAdvanced = new Set(manifest.advanced_fields ?? [])
  let primaryFields = fields.filter((field) => field.required || preferred.has(field.name))
  if (primaryFields.length === 0 && fields.length > 0) {
    primaryFields = fields.slice(0, Math.min(2, fields.length))
  }
  const primaryNames = new Set(primaryFields.map((field) => field.name))
  const advancedFields = fields.filter(
    (field) => explicitAdvanced.has(field.name) || !primaryNames.has(field.name),
  )
  const wiredOutputHandleSet = new Set(wiredOutputHandles)
  const rules = Array.isArray(values.rules) ? values.rules as ConditionRuleValue[] : []
  const rulesReady = rules.length > 0 && rules.every(
    (rule) => rule.field?.trim()
      && rule.operator
      && (VALUELESS_OPERATORS.has(rule.operator) || !isEmpty(rule.value)),
  )
  const missingRequired = manifest.type === 'condition.rules'
    ? (rulesReady ? [] : ['At least one complete rule'])
    : fields.filter((f) => f.required && isEmpty(values[f.name])).map((f) => f.title)

  function handleSave() {
    if (manifest.type === 'condition.rules') {
      onSave({
        match: values.match === 'any' ? 'any' : 'all',
        rules: rules.map((rule) => ({
          field: rule.field.trim(),
          operator: rule.operator,
          ...(!VALUELESS_OPERATORS.has(rule.operator) ? { value: rule.value } : {}),
        })),
      })
      return
    }
    // Drop empty strings so optional fields don't persist as ""
    const clean: Record<string, unknown> = {}
    for (const f of fields) {
      const v = values[f.name]
      if (isEmpty(v)) continue
      clean[f.name] = f.type === 'integer' || f.type === 'number' ? Number(v) : v
    }
    onSave(clean)
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-start justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
        <div className="min-w-0">
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-brand-500">{categoryLabel(manifest.category)}</p>
          <p className="truncate text-sm font-bold text-slate-900 dark:text-white">{manifest.display_name || nodeLabel(manifest.type)}</p>
          <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{manifest.summary}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="Close"
          aria-label="Close config panel"
          className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800"
        >
          <X size={16} />
        </button>
      </div>

      {/* Fields */}
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {manifest.type === 'condition.rules' ? (
          <RulesEditor
            nodeId={nodeId}
            match={values.match === 'any' ? 'any' : 'all'}
            rules={rules}
            onMatchChange={(match) => setField('match', match)}
            onRulesChange={(next) => setField('rules', next)}
          />
        ) : fields.length === 0 ? (
          <p className="text-xs text-slate-500">This node has no configurable fields.</p>
        ) : (
          <>
            {manifest.type === 'ai.enrich' && (
              <EnrichmentStageFields
                provider={String(values.enrich_source ?? '')}
                connectionName={String(values.connection_name ?? '')}
                linkfinderType={String(values.linkfinder_type ?? '')}
                connections={connections}
                onChange={(provider, connectionName) => {
                  setField('enrich_source', provider)
                  setField('connection_name', connectionName)
                  if (provider === 'linkfinder' && !values.linkfinder_type) setField('linkfinder_type', 'linkedin_profile_to_email')
                }}
                onLinkFinderTypeChange={(lookupType) => setField('linkfinder_type', lookupType)}
              />
            )}
            {primaryFields.filter((f) => (
              manifest.type !== 'ai.enrich' || !['enrich_source', 'connection_name', 'linkfinder_type'].includes(f.name)
            )).map((f) => (
              <Field key={f.name} field={f} value={values[f.name]} onChange={(v) => setField(f.name, v)} />
            ))}
            {advancedFields.length > 0 && (
              <div className="rounded-xl border border-slate-100 dark:border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAdvanced((visible) => !visible)}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left"
                >
                  <span>
                    <span className="block text-xs font-semibold text-slate-700 dark:text-slate-200">Advanced settings</span>
                    <span className="block text-[11px] text-slate-400">
                      {advancedFields.length} optional {advancedFields.length === 1 ? 'setting' : 'settings'} · defaults are usually best
                    </span>
                  </span>
                  {showAdvanced ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
                </button>
                {showAdvanced && (
                  <div className="space-y-4 border-t border-slate-100 px-3 py-3 dark:border-slate-800">
                    {advancedFields.filter((f) => (
                      manifest.type !== 'ai.enrich' || f.name !== 'linkfinder_type'
                    )).map((f) => (
                      <Field key={f.name} field={f} value={values[f.name]} onChange={(v) => setField(f.name, v)} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* Output handles reference */}
        {manifest.output_handles.length > 0 && (
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Routes</p>
            <p className="mt-1 text-[11px] leading-relaxed text-slate-500">
              Each output is an explicit branch. Unconnected routes intentionally end the sequence.
            </p>
            <ul className="mt-2 space-y-1.5">
              {manifest.output_handles.map((h) => {
                const wired = wiredOutputHandleSet.has(h.name)
                const danger = isFailureRoute(h.name)
                return (
                  <li key={h.name} className="rounded-lg border border-white/70 bg-white px-2.5 py-2 text-[11px] dark:border-slate-700 dark:bg-slate-900/50">
                    <div className="flex items-center justify-between gap-2">
                      <span className={clsx('font-bold uppercase tracking-wide', danger ? 'text-rose-500' : 'text-emerald-600')}>{handleLabel(h.name)}</span>
                      <span className={clsx(
                        'rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide',
                        wired
                          ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                          : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300',
                      )}>
                        {wired ? 'Connected' : 'Ends here'}
                      </span>
                    </div>
                    <p className="mt-1 leading-relaxed text-slate-500">{h.description || routeFallback(h.name)}</p>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="space-y-2 border-t border-slate-100 px-4 py-3 dark:border-slate-800">
        {missingRequired.length > 0 && (
          <p className="rounded-md bg-amber-50 px-2.5 py-1.5 text-[11px] text-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
            Required: {missingRequired.join(', ')}
          </p>
        )}
        <div className="flex items-center justify-between gap-2">
          {onDelete ? (
            <Button variant="danger" size="sm" icon={Trash2} onClick={onDelete}>Delete</Button>
          ) : <span />}
          <Button variant="primary" size="sm" icon={Save} onClick={handleSave} isLoading={saving} disabled={missingRequired.length > 0}>
            Save
          </Button>
        </div>
      </div>
    </div>
  )
}

const ENRICHMENT_PROVIDER_NAMES: Record<string, string> = {
  apollo: 'Apollo',
  proxycurl: 'Proxycurl',
  hunter: 'Hunter',
  linkfinder: 'LinkFinder',
}

const LINKFINDER_LOOKUP_TYPES = [
  'linkedin_profile_to_email',
  'linkedin_profile_to_phone',
  'linkedin_profile_to_linkedin_info',
  'email_to_linkedin_url',
  'email_to_profile',
  'email_to_phone',
  'phone_to_linkedin_url',
  'phone_to_profile',
  'phone_to_email',
  'lead_full_name_to_linkedin_url',
  'company_name_to_website',
  'company_name_to_phone',
  'company_name_to_email',
  'company_name_to_employee_count',
  'company_name_to_linkedin_url',
] as const

function isFailureRoute(handle: string): boolean {
  return ['on_error', 'rejected', 'timeout', 'empty', 'false'].includes(handle)
}

function routeFallback(handle: string): string {
  return handle === 'default'
    ? 'Continue to the next step.'
    : `Follow the ${handleLabel(handle)} branch.`
}

function EnrichmentStageFields({
  provider,
  connectionName,
  linkfinderType,
  connections,
  onChange,
  onLinkFinderTypeChange,
}: {
  provider: string
  connectionName: string
  linkfinderType: string
  connections: Connection[]
  onChange: (provider: string, connectionName: string) => void
  onLinkFinderTypeChange: (lookupType: string) => void
}) {
  const availableProviders = ['apollo', 'proxycurl', 'hunter', 'linkfinder'].filter(
    (candidate) => connections.some((connection) => connection.provider === candidate)
      || candidate === provider,
  )
  const providerConnections = connections.filter((connection) => connection.provider === provider)

  return (
    <div className="space-y-3 rounded-xl border border-brand-100 bg-brand-50/40 p-3 dark:border-brand-900/50 dark:bg-brand-950/20">
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-600 dark:text-brand-300">Provider</p>
        <Select
          className="mt-1"
          size="sm"
          ariaLabel="Enrichment provider"
          value={provider}
          onChange={(nextProvider) => {
            const nextConnection = connections.find((connection) => connection.provider === nextProvider)
            onChange(nextProvider, nextConnection?.name ?? '')
          }}
          options={availableProviders.map((candidate) => ({
            value: candidate,
            label: ENRICHMENT_PROVIDER_NAMES[candidate] ?? candidate,
          }))}
        />
      </div>
      <div>
        <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-600 dark:text-brand-300">Connected account</p>
        {providerConnections.length > 0 ? (
          <Select
            className="mt-1"
            size="sm"
            ariaLabel="Enrichment connection"
            value={connectionName}
            onChange={(nextConnection) => onChange(provider, nextConnection)}
            options={providerConnections.map((connection) => ({
              value: connection.name,
              label: connection.name,
            }))}
          />
        ) : (
          <p className="mt-1 rounded-md bg-amber-50 px-2.5 py-2 text-[11px] text-amber-700 dark:bg-amber-950/30 dark:text-amber-300">
            This provider is not connected. Add it in Integrations before running the campaign.
          </p>
        )}
      </div>
      {provider === 'linkfinder' && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-600 dark:text-brand-300">Lookup type</p>
          <Select
            className="mt-1"
            size="sm"
            ariaLabel="LinkFinder lookup type"
            value={linkfinderType || 'linkedin_profile_to_email'}
            onChange={onLinkFinderTypeChange}
            options={LINKFINDER_LOOKUP_TYPES.map((lookupType) => ({
              value: lookupType,
              label: lookupType,
            }))}
          />
        </div>
      )}
      <p className="text-[11px] leading-relaxed text-slate-500">
        This stage uses one credential only. Provider failures follow the visible On error edge.
      </p>
    </div>
  )
}

function isEmpty(v: unknown): boolean {
  return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0)
}

const inputCls =
  'w-full rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-[13px] text-slate-800 transition-colors focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-800 dark:text-white'

function Field({ field, value, onChange }: { field: SchemaField; value: unknown; onChange: (v: unknown) => void }) {
  if (field.type === 'boolean') {
    return (
      <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg border border-slate-100 px-2.5 py-2 dark:border-slate-800">
        <span className="min-w-0">
          <span className="text-[12px] font-semibold text-slate-700 dark:text-slate-200">{field.title}</span>
          {field.description && <p className="text-[11px] leading-tight text-slate-400">{field.description}</p>}
        </span>
        <input
          type="checkbox"
          checked={Boolean(value ?? field.default)}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 flex-shrink-0 rounded border-slate-300 text-brand-500 focus:ring-brand-400"
        />
      </label>
    )
  }

  return (
    <label className="block">
      <span className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          {field.title}
          {field.required && <span className="ml-0.5 text-rose-500">*</span>}
        </span>
        {field.enumValues && <span className="text-[9px] uppercase tracking-wider text-slate-300">choice</span>}
      </span>
      {field.description && <p className="mb-1 mt-0.5 text-[11px] leading-tight text-slate-400">{field.description}</p>}
      {field.type === 'enum' ? (
        <Select
          className="mt-0.5"
          size="sm"
          ariaLabel={field.name}
          value={String(value ?? field.default ?? '')}
          onChange={(v) => onChange(v)}
          options={(field.enumValues ?? []).map((opt) => ({ value: opt, label: opt }))}
        />
      ) : field.isLong ? (
        <textarea
          rows={4}
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.default != null ? String(field.default) : 'Supports {{contact.first_name}} variables'}
          className={clsx(inputCls, 'mt-0.5 resize-y font-mono text-[12px] leading-relaxed')}
        />
      ) : (
        <input
          type={field.type === 'integer' || field.type === 'number' ? 'number' : field.format === 'email' ? 'email' : 'text'}
          value={value == null ? '' : String(value)}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.default != null ? String(field.default) : ''}
          className={clsx(inputCls, 'mt-0.5')}
        />
      )}
    </label>
  )
}

function RulesEditor({
  nodeId,
  match,
  rules,
  onMatchChange,
  onRulesChange,
}: {
  nodeId: string
  match: 'all' | 'any'
  rules: ConditionRuleValue[]
  onMatchChange: (value: 'all' | 'any') => void
  onRulesChange: (rules: ConditionRuleValue[]) => void
}) {
  const visibleRules = rules.length > 0 ? rules : [{ field: '', operator: 'equals', value: '' }]
  const updateRule = (index: number, patch: Partial<ConditionRuleValue>) => {
    const next = visibleRules.map((rule, i) => i === index ? { ...rule, ...patch } : rule)
    onRulesChange(next)
  }
  const removeRule = (index: number) => {
    onRulesChange(visibleRules.filter((_rule, i) => i !== index))
  }

  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-brand-50/60 p-3 dark:bg-brand-950/20">
        <p className="text-xs font-semibold text-brand-800 dark:text-brand-200">Continue down “Matched” when</p>
        <div className="mt-2 flex gap-2">
          {(['all', 'any'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => onMatchChange(mode)}
              className={clsx(
                'rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors',
                match === mode
                  ? 'bg-brand-600 text-white'
                  : 'bg-white text-slate-600 hover:bg-brand-100 dark:bg-slate-900 dark:text-slate-300',
              )}
            >
              {mode === 'all' ? 'All rules match' : 'Any rule matches'}
            </button>
          ))}
        </div>
      </div>

      <datalist id={`condition-fields-${nodeId}`}>
        {COMMON_FIELDS.map((field) => <option key={field} value={field} />)}
      </datalist>

      {visibleRules.map((rule, index) => (
        <div key={index} className="space-y-2 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Rule {index + 1}</span>
            <button
              type="button"
              onClick={() => removeRule(index)}
              aria-label={`Remove rule ${index + 1}`}
              className="rounded-md p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-950/30"
            >
              <Trash2 size={13} />
            </button>
          </div>
          <input
            value={rule.field}
            onChange={(e) => updateRule(index, { field: e.target.value })}
            list={`condition-fields-${nodeId}`}
            placeholder="Choose a field, e.g. company"
            className={inputCls}
          />
          <Select
            size="sm"
            ariaLabel={`Operator for rule ${index + 1}`}
            value={rule.operator}
            onChange={(operator) => updateRule(index, { operator })}
            options={CONDITION_OPERATORS}
          />
          {!VALUELESS_OPERATORS.has(rule.operator) && (
            <input
              value={String(rule.value ?? '')}
              onChange={(e) => updateRule(index, { value: e.target.value })}
              placeholder={rule.operator.includes('one_of') ? 'Value one, value two' : 'Comparison value'}
              className={inputCls}
            />
          )}
          <p className="text-[10px] leading-4 text-slate-400">
            Text comparisons are case-insensitive. Numeric operators require numeric values.
          </p>
        </div>
      ))}

      <Button
        type="button"
        variant="ghost"
        size="sm"
        icon={Plus}
        onClick={() => onRulesChange(visibleRules.concat({ field: '', operator: 'equals', value: '' }))}
      >
        Add rule
      </Button>
    </div>
  )
}
