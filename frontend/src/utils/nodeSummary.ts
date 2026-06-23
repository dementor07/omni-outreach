import type { NodeManifest } from '../api/v2'
import { fieldLabel } from './fieldLabel'

const OPERATOR_LABELS: Record<string, string> = {
  equals: 'is',
  not_equals: 'is not',
  contains: 'contains',
  not_contains: 'does not contain',
  starts_with: 'starts with',
  ends_with: 'ends with',
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
  one_of: 'is one of',
  not_one_of: 'is not one of',
  is_set: 'is set',
  is_not_set: 'is not set',
  is_true: 'is true',
  is_false: 'is false',
  regex: 'matches',
}

function short(value: unknown, max = 52): string {
  const text = String(value ?? '').trim()
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

export function nodeConfigSummary(
  manifest: NodeManifest,
  config: Record<string, unknown>,
): string | null {
  if (manifest.type === 'condition.rules') {
    const rules = Array.isArray(config.rules) ? config.rules as Array<Record<string, unknown>> : []
    if (rules.length === 0) return 'Add at least one rule'
    const first = rules[0]
    const field = fieldLabel(String(first.field ?? 'field'))
    const operator = OPERATOR_LABELS[String(first.operator ?? '')] ?? String(first.operator ?? '')
    const value = ['is_set', 'is_not_set', 'is_true', 'is_false'].includes(String(first.operator))
      ? ''
      : ` ${short(first.value, 22)}`
    const prefix = config.match === 'any' ? 'Any' : 'All'
    return rules.length === 1
      ? `${field} ${operator}${value}`
      : `${prefix} ${rules.length} rules · ${field} ${operator}${value}`
  }

  if (manifest.type === 'condition.field_match') {
    const field = fieldLabel(String(config.field_path ?? 'field'))
    const operator = OPERATOR_LABELS[String(config.operator ?? 'equals')] ?? String(config.operator ?? '')
    return `${field} ${operator} ${short(config.value, 22)}`.trim()
  }

  if (manifest.type === 'ai.enrich') {
    const provider = String(config.enrich_source ?? 'Provider')
    const connection = String(config.connection_name ?? '')
    const policy = config.merge_policy === 'overwrite' ? 'may overwrite' : 'fills missing fields'
    return `${provider.charAt(0).toUpperCase()}${provider.slice(1)} · ${policy}${connection ? ` · ${connection}` : ''}`
  }

  const keys = Object.keys(config)
  if (keys.length === 0) return null
  const preferred = [
    'subject_template',
    'body_template',
    'instruction',
    'icp_description',
    'new_stage',
    'title_template',
    'amount',
    'connection_name',
    'url',
    'channel',
  ]
  for (const key of preferred) {
    const value = config[key]
    if (typeof value === 'string' && value.trim()) return short(value)
    if (typeof value === 'number') return String(value)
  }
  const first = config[keys[0]]
  return typeof first === 'string' ? short(first) : `${keys.length} settings`
}
