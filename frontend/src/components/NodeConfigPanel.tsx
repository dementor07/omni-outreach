import { useEffect, useMemo, useState } from 'react'
import { X, Trash2, Save } from 'lucide-react'
import { clsx } from 'clsx'
import type { NodeManifest } from '../api/v2'
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
      title: prop.title ?? name,
      description: prop.description,
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
  onSave: (config: Record<string, unknown>) => void
  onDelete: () => void
  onClose: () => void
}

export default function NodeConfigPanel({
  manifest,
  nodeId,
  initialConfig,
  saving,
  onSave,
  onDelete,
  onClose,
}: NodeConfigPanelProps) {
  const fields = useMemo(() => fieldsFromSchema(manifest.config_schema as JsonSchema), [manifest])
  const [values, setValues] = useState<Record<string, unknown>>(initialConfig)

  // Reset the form when switching to a different node.
  useEffect(() => {
    setValues(initialConfig)
  }, [nodeId, initialConfig])

  function setField(name: string, value: unknown) {
    setValues((v) => ({ ...v, [name]: value }))
  }

  const missingRequired = fields.filter((f) => f.required && isEmpty(values[f.name])).map((f) => f.title)

  function handleSave() {
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
          <p className="text-[9px] font-bold uppercase tracking-[0.18em] text-brand-500">{manifest.category}</p>
          <p className="truncate text-sm font-bold text-slate-900 dark:text-white">{manifest.type}</p>
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
        {fields.length === 0 ? (
          <p className="text-xs text-slate-500">This node has no configurable fields.</p>
        ) : (
          fields.map((f) => <Field key={f.name} field={f} value={values[f.name]} onChange={(v) => setField(f.name, v)} />)
        )}

        {/* Output handles reference */}
        {manifest.output_handles.length > 0 && (
          <div className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/50">
            <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400">Outputs</p>
            <ul className="mt-1.5 space-y-1">
              {manifest.output_handles.map((h) => (
                <li key={h.name} className="flex items-baseline gap-2 text-[11px]">
                  <span className={clsx('font-mono font-semibold', h.name === 'on_error' ? 'text-rose-500' : 'text-emerald-600')}>{h.name}</span>
                  <span className="text-slate-500">{h.description}</span>
                </li>
              ))}
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
          <Button variant="danger" size="sm" icon={Trash2} onClick={onDelete}>Delete</Button>
          <Button variant="primary" size="sm" icon={Save} onClick={handleSave} isLoading={saving} disabled={missingRequired.length > 0}>
            Save
          </Button>
        </div>
      </div>
    </div>
  )
}

function isEmpty(v: unknown): boolean {
  return v === undefined || v === null || v === ''
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
