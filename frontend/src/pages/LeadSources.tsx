import { useQuery } from '@tanstack/react-query'
import { Database } from 'lucide-react'
import { nodes, integrations, type NodeManifest } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'

export default function LeadSources() {
  const nodesQ = useQuery({ queryKey: ['node-manifests'], queryFn: nodes.list })
  const connsQ = useQuery({ queryKey: ['connections'], queryFn: () => integrations.list() })

  const sources = (nodesQ.data ?? []).filter((m) => m.category === 'SOURCE')
  const connectedProviders = new Set((connsQ.data ?? []).map((c) => c.provider))

  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Lead Sources"
        eyebrow="Setup"
        title="Lead Sources"
        description="Where your leads come from. Each source is a node you can drop into a campaign."
      />

      {nodesQ.isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 skeleton rounded-2xl" />)}</div>
      ) : sources.length === 0 ? (
        <Card><EmptyState icon={Database} title="No source nodes registered" description="Source nodes (Apollo, Hunter, Sheets, …) will appear here." /></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sources.map((s) => <SourceCard key={s.type} s={s} connected={isConnected(s.type, connectedProviders)} />)}
        </div>
      )}
    </div>
  )
}

function isConnected(nodeType: string, providers: Set<string>): boolean {
  // node type is like "source.apollo" → provider "apollo"
  const provider = nodeType.split('.')[1]
  return provider ? providers.has(provider) : false
}

function SourceCard({ s, connected }: { s: NodeManifest; connected: boolean }) {
  return (
    <Card padding="md">
      <div className="flex items-start justify-between gap-2">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-50 text-sky-600 dark:bg-sky-900/30">
          <Database size={16} />
        </span>
        <Badge label={connected ? 'connected' : 'not connected'} variant={connected ? 'success' : 'neutral'} size="xs" dot />
      </div>
      <p className="mt-3 text-sm font-semibold text-slate-900 dark:text-white">{s.type}</p>
      <p className="mt-0.5 text-xs text-slate-500">{s.summary}</p>
    </Card>
  )
}
