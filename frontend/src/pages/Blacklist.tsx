import { ShieldOff } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'

export default function Blacklist() {
  return (
    <div className="space-y-6">
      <PageHeader
        screenLabel="Blacklist"
        eyebrow="Setup"
        title="Blacklist"
        description="Domains and addresses to suppress across every campaign — unsubscribes, competitors, do-not-contact."
      />
      <Card>
        <EmptyState
          icon={ShieldOff}
          title="No suppression rules yet"
          description="Unsubscribe replies are auto-suppressed via the inbox classifier. Manual blacklist rules will live here."
        />
      </Card>
    </div>
  )
}
