import React, { useMemo, useState } from 'react'
import { Trash2, ChevronUp, ChevronDown, Save, Plus, Settings2, Zap } from 'lucide-react'
import { Node, Edge } from '@xyflow/react'
import { clsx } from 'clsx'
import type { NodeManifest } from '../api/v2'
import { nodeIcon } from '../utils/nodeIcons'
import { visualFor } from '../utils/nodeVisuals'
import { nodeLabel as nodeLabelFor } from '../utils/nodeLabel'
import Badge from './Badge'
import Button from './Button'
import Card from './Card'

/* The Linear builder — a vertical-timeline editor over the SAME v2 manifest
 * nodes the canvas uses. It is fully congruent with CampaignEditor: same node
 * shape ({ manifest, config }), same icon source (nodeIcon), same category
 * accents (CATEGORY_VISUAL). It linearizes the graph into an ordered chain;
 * adding/removing/reordering rewrites the edges as a single spine. */

interface OmniNodeData extends Record<string, unknown> {
  manifest: NodeManifest
  config: Record<string, unknown>
}
type OmniNode = Node<OmniNodeData>

interface Props {
  nodes: OmniNode[]
  edges: Edge[]
  manifests: NodeManifest[]
  onChange: (nodes: OmniNode[], edges: Edge[]) => void
  onSave: () => void
  onEditNode: (id: string) => void
  isSaving?: boolean
}

// The label shown on a step — the shared human node name (curated, falls back
// to a prettified type tail for unknown types).
function nodeLabel(manifest: NodeManifest): string {
  return manifest.display_name || nodeLabelFor(manifest.type)
}

// Chain the nodes head-to-tail by array order via their 'default'/first handle.
function rechain(nodes: OmniNode[], existing: Edge[]): Edge[] {
  const edges: Edge[] = []
  for (let i = 0; i < nodes.length - 1; i++) {
    const src = nodes[i]
    const tgt = nodes[i + 1]
    const handle = src.data.manifest.output_handles[0]?.name ?? 'default'
    // Preserve any existing edge id for this pair so React keys stay stable.
    const prior = existing.find((e) => e.source === src.id && e.target === tgt.id)
    edges.push({
      id: prior?.id ?? `e_${src.id}_${tgt.id}`,
      source: src.id,
      target: tgt.id,
      sourceHandle: handle,
      targetHandle: 'in',
    })
  }
  return edges
}

export default function SequentialBuilder({ nodes, edges, manifests, onChange, onSave, onEditNode, isSaving }: Props) {
  const [showPalette, setShowPalette] = useState(false)

  const addNode = (manifest: NodeManifest) => {
    const newNode: OmniNode = {
      id: crypto.randomUUID(),
      type: 'omni',
      position: { x: 120, y: 80 + nodes.length * 130 },
      data: { manifest, config: {} },
    }
    const next = [...nodes, newNode]
    onChange(next, rechain(next, edges))
    setShowPalette(false)
  }

  const removeNode = (id: string) => {
    const next = nodes.filter((n) => n.id !== id)
    onChange(next, rechain(next, edges))
  }

  const moveNode = (index: number, dir: 'up' | 'down') => {
    const target = dir === 'up' ? index - 1 : index + 1
    if (target < 0 || target >= nodes.length) return
    const next = [...nodes]
    ;[next[index], next[target]] = [next[target], next[index]]
    onChange(next, rechain(next, edges))
  }

  // Palette grouped by category — same source of truth as the canvas palette.
  const grouped = useMemo(() => {
    const map = new Map<string, NodeManifest[]>()
    for (const m of manifests) {
      if (m.visible_in_palette === false) continue
      const arr = map.get(m.category) ?? []
      arr.push(m)
      map.set(m.category, arr)
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [manifests])

  return (
    <div className="mx-auto max-w-3xl space-y-10 py-8">
      <div className="flex items-center justify-between px-6">
        <div>
          <h3 className="text-[18px] font-bold tracking-tight text-slate-900 dark:text-white">Linear sequence</h3>
          <p className="mt-0.5 text-sm text-slate-500">The same workflow as the canvas, as an ordered timeline.</p>
        </div>
        <Button variant="primary" size="sm" icon={Save} isLoading={isSaving} onClick={onSave}>Save</Button>
      </div>

      <div className="relative space-y-5 px-6">
        <div className="absolute left-[39px] top-6 bottom-6 w-0.5 bg-slate-100 dark:bg-slate-800" />

        {/* Start marker */}
        <div className="relative z-10 flex items-center gap-6">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-50 text-brand-600 dark:bg-brand-900/30">
              <Zap size={18} fill="currentColor" />
            </div>
          </div>
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-brand-500">Sequence start</p>
        </div>

        {nodes.length === 0 ? (
          <div className="ml-24 rounded-2xl border-2 border-dashed border-slate-200 bg-white/50 p-10 text-center dark:border-slate-800 dark:bg-slate-900/30">
            <h4 className="font-bold text-slate-400">Empty pipeline</h4>
            <p className="mt-1 text-sm text-slate-400">Add a step below to start building.</p>
          </div>
        ) : (
          nodes.map((node, i) => {
            const { manifest } = node.data
            const v = visualFor(manifest.category)
            const Icon = nodeIcon(manifest, v.icon)
            const schema = manifest.config_schema as { required?: string[] }
            const missing = (schema.required ?? []).filter((k) => {
              const val = node.data.config[k]
              return val === undefined || val === null || val === ''
            })
            return (
              <div key={node.id} className="group relative z-10 flex items-start gap-6">
                <div className="flex h-20 w-20 shrink-0 items-center justify-center">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-white bg-slate-100 text-xs font-black text-slate-400 shadow-sm transition-all group-hover:bg-brand-500 group-hover:text-white dark:border-slate-950 dark:bg-slate-800">
                    {i + 1}
                  </div>
                </div>
                <Card padding="none" className="flex-1 transition-all group-hover:border-brand-200 group-hover:shadow-md">
                  <div className="flex items-center gap-4 p-4">
                    <div className={clsx('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl', v.tint, v.accent)}>
                      <Icon size={18} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-[15px] font-bold text-slate-900 dark:text-white">{nodeLabel(manifest)}</p>
                        {missing.length > 0 && <Badge label="Needs config" variant="warning" size="xs" />}
                      </div>
                      <p className="mt-0.5 truncate text-[11px] font-medium text-slate-400">{manifest.summary}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      <div className="mr-1 flex flex-col border-r border-slate-100 pr-1 dark:border-slate-800">
                        <button type="button" onClick={() => moveNode(i, 'up')} disabled={i === 0} className="p-1 text-slate-300 transition-colors hover:text-brand-500 disabled:opacity-20"><ChevronUp size={15} /></button>
                        <button type="button" onClick={() => moveNode(i, 'down')} disabled={i === nodes.length - 1} className="p-1 text-slate-300 transition-colors hover:text-brand-500 disabled:opacity-20"><ChevronDown size={15} /></button>
                      </div>
                      <Button variant="secondary" size="sm" icon={Settings2} onClick={() => onEditNode(node.id)}>Edit</Button>
                      <button type="button" onClick={() => removeNode(node.id)} className="rounded-xl p-2 text-slate-300 transition-colors hover:bg-rose-50 hover:text-rose-500 dark:hover:bg-rose-900/20"><Trash2 size={17} /></button>
                    </div>
                  </div>
                </Card>
              </div>
            )
          })
        )}

        {/* End marker */}
        <div className="relative z-10 flex items-center gap-6">
          <div className="flex h-20 w-20 shrink-0 items-center justify-center">
            <div className="h-3.5 w-3.5 rounded-full border-4 border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-950" />
          </div>
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-400">End of sequence</p>
        </div>
      </div>

      {/* Add-step palette */}
      <div className="px-6">
        {!showPalette ? (
          <button
            type="button"
            onClick={() => setShowPalette(true)}
            className="ml-24 flex items-center gap-2 rounded-xl border-2 border-dashed border-slate-200 px-4 py-3 text-sm font-semibold text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-600 dark:border-slate-800"
          >
            <Plus size={16} /> Add step
          </button>
        ) : (
          <div className="ml-24 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-[11px] font-bold uppercase tracking-[0.15em] text-slate-400">Add a step</p>
              <button type="button" onClick={() => setShowPalette(false)} className="text-xs text-slate-400 hover:text-slate-600">Close</button>
            </div>
            <div className="space-y-3">
              {grouped.map(([category, items]) => {
                const v = visualFor(category)
                return (
                  <div key={category}>
                    <p className={clsx('mb-1 text-[9px] font-bold uppercase tracking-[0.18em]', v.accent)}>{category}</p>
                    <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                      {items.map((m) => {
                        const Icon = nodeIcon(m, v.icon)
                        return (
                          <button
                            key={m.type}
                            type="button"
                            onClick={() => addNode(m)}
                            title={m.summary}
                            className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-800"
                          >
                            <span className={clsx('flex h-5 w-5 shrink-0 items-center justify-center rounded', v.tint, v.accent)}>
                              <Icon size={12} />
                            </span>
                            <span className="truncate">{nodeLabel(m)}</span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
