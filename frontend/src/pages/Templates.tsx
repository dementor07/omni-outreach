import { FileText } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'

export default function Templates() {
  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Templates"
        eyebrow="Setup"
        title="Templates"
        description="Reusable message templates for your campaigns, with variables and AI-assisted drafting."
      />
      <Card>
        <EmptyState
          icon={FileText}
          title="Templates are managed inside campaigns"
          description="In v2, message copy lives on channel + ai.compose nodes within each campaign. A shared template library will surface here."
        />
      </Card>
    </div>
  )
}
