import React from 'react'
import { Plus, RefreshCw, MoreHorizontal, Trash2, Users, Send, CheckCircle2, AlertCircle, Search, Mail, Linkedin, MessageSquare, Smartphone, Phone, LayoutDashboard, GitBranch, BarChart3, ArrowUpRight, Sparkles } from 'lucide-react'
import PageHeader from '../components/PageHeader'
import Button from '../components/Button'
import Card from '../components/Card'
import StatCard from '../components/StatCard'
import Badge from '../components/Badge'
import Tabs from '../components/Tabs'
import { clsx } from 'clsx'

const I = { Plus, RefreshCw, MoreHorizontal, Trash2, Users, Send, CheckCircle2, AlertCircle, Search, Mail, Linkedin, MessageSquare, Smartphone, Phone, LayoutDashboard, GitBranch, BarChart3, ArrowUpRight, Sparkles }

export default function StyleGuide() {
  return (
    <div className="space-y-8">
      <PageHeader
        screenLabel="Style guide"
        eyebrow="Design system"
        title="Style guide"
        description="The unified pattern every screen composes. One radius, one type ramp, one filter bar, one button hierarchy."
        actions={<Button variant="secondary" size="md" icon={I.ArrowUpRight}>View in repo</Button>}
      />

      <SGSection title="Type ramp" description="Inter. Single ramp across the entire app.">
        <div className="space-y-3">
          <SGRow tag="Page title" cls="text-[22px] font-semibold tracking-tight">Mission control for outreach</SGRow>
          <SGRow tag="Section title" cls="text-[15px] font-semibold">Daily activity</SGRow>
          <SGRow tag="Body" cls="text-sm text-slate-700">Live state of every campaign, channel, and lead.</SGRow>
          <SGRow tag="Caption" cls="text-[13px] text-slate-500">14 day rolling window</SGRow>
          <SGRow tag="Eyebrow" cls="text-[11px] font-semibold uppercase tracking-[0.18em] text-brand-500">Mission control</SGRow>
          <SGRow tag="Tabular" cls="text-2xl font-semibold tabular-nums">12,480</SGRow>
        </div>
      </SGSection>

      <SGSection title="Color tokens" description="Brand swappable via CSS variables. Neutrals stay slate.">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          {['brand', 'emerald', 'amber', 'rose', 'violet'].map((c) => <SwatchRow key={c} name={c} />)}
        </div>
      </SGSection>

      <SGSection title="Buttons" description="3 sizes × 4 variants. One radius (rounded-lg). One font weight (semibold).">
        <div className="space-y-4">
          {(['md', 'sm', 'xs'] as const).map((sz) => (
            <div key={sz} className="flex flex-wrap items-center gap-3">
              <span className="w-12 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{sz}</span>
              <Button size={sz} variant="primary" icon={I.Plus}>Primary</Button>
              <Button size={sz} variant="secondary" icon={I.RefreshCw}>Secondary</Button>
              <Button size={sz} variant="ghost" icon={I.MoreHorizontal}>Ghost</Button>
              <Button size={sz} variant="danger" icon={I.Trash2}>Danger</Button>
            </div>
          ))}
        </div>
      </SGSection>

      <SGSection title="Badges" description="Status + channel variants share a single shape.">
        <div className="flex flex-wrap items-center gap-2">
          {['queued','locked','sent','failed','skipped','active','paused','live','simulation','positive','negative'].map((s) => (
            <Badge key={s} label={s} asStatus dot />
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {['email','linkedin_dm','linkedin_inmail','whatsapp','sms','voice'].map((c) => (
            <Badge key={c} label={c} asChannel />
          ))}
        </div>
      </SGSection>

      <SGSection title="Stat cards" description="One density. Trend pill is optional.">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Total leads" value={12480} icon={I.Users} accent="brand" trend={12} />
          <StatCard label="Invited" value={9120} icon={I.Send} accent="emerald" trend={4} />
          <StatCard label="Accepted" value={3140} icon={I.CheckCircle2} accent="amber" trend={-2} />
          <StatCard label="Failed" value={86} icon={I.AlertCircle} accent="rose" />
        </div>
      </SGSection>

      <SGSection title="Tabs" description="Underline only. No pill chrome.">
        <Tabs
          value="leads"
          onChange={() => {}}
          items={[
            { value: 'overview', label: 'Overview', icon: I.LayoutDashboard },
            { value: 'leads', label: 'Leads', icon: I.Users, count: 1248 },
            { value: 'sequence', label: 'Sequence', icon: I.GitBranch },
            { value: 'analytics', label: 'Analytics', icon: I.BarChart3 },
          ]}
        />
      </SGSection>
    </div>
  )
}

function SGSection({ title, description, children }: { title: string, description?: string, children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      <Card padding="lg">{children}</Card>
    </section>
  )
}

function SGRow({ tag, cls, children }: { tag: string, cls: string, children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-4">
      <span className="w-28 flex-shrink-0 text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">{tag}</span>
      <span className={clsx(cls, 'text-slate-900 dark:text-white')}>{children}</span>
    </div>
  )
}

function SwatchRow({ name }: { name: string }) {
  const ramps: Record<string, string[]> = {
    brand:   ['bg-brand-50', 'bg-brand-100', 'bg-brand-200', 'bg-brand-300', 'bg-brand-400', 'bg-brand-500'],
    emerald: ['bg-emerald-50', 'bg-emerald-100', 'bg-emerald-200', 'bg-emerald-300', 'bg-emerald-400', 'bg-emerald-500'],
    amber:   ['bg-amber-50', 'bg-amber-100', 'bg-amber-200', 'bg-amber-300', 'bg-amber-400', 'bg-amber-500'],
    rose:    ['bg-rose-50', 'bg-rose-100', 'bg-rose-200', 'bg-rose-300', 'bg-rose-400', 'bg-rose-500'],
    violet:  ['bg-violet-50', 'bg-violet-100', 'bg-violet-200', 'bg-violet-300', 'bg-violet-400', 'bg-violet-500'],
  }
  return (
    <div className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{name}</span>
      </div>
      <div className="grid grid-cols-6 gap-1">
        {ramps[name].map((c, i) => (
          <div key={i} className={clsx('aspect-square rounded', c)} />
        ))}
      </div>
    </div>
  )
}
