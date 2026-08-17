import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Sparkles, ChevronRight } from 'lucide-react'
import { tones, type Tone } from '../api/v2'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'

function ChipList({ label, items }: { label: string; items?: string[] }) {
  if (!items || items.length === 0) return null
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</p>
      <ul className="space-y-1">
        {items.map((it, i) => (
          <li key={i} className="text-sm text-slate-600 dark:text-slate-300">
            • {it}
          </li>
        ))}
      </ul>
    </div>
  )
}

function ToneDetail({ tone }: { tone: Tone }) {
  const s = tone.spec
  const wc = s.word_count
  return (
    <div className="space-y-5">
      <div>
        <p className="text-sm text-slate-600 dark:text-slate-300">{tone.description}</p>
        {wc && (
          <p className="mt-2 text-xs text-slate-400">
            Target length: ~{wc.recommended ?? wc.max} words (max {wc.max})
            {wc.rationale ? ` — ${wc.rationale}` : ''}
          </p>
        )}
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <ChipList label="Voice & personality" items={s.personality_traits} />
        <ChipList label="How to open" items={s.opening_styles} />
        <ChipList label="Delivering value" items={s.value_delivery} />
        <ChipList label="How to close" items={s.closing_approaches} />
        <ChipList label="Personalise using" items={s.personalization_hooks} />
        <ChipList label="Never do" items={s.avoid} />
      </div>
      {s.example_template?.body && (
        <div className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Example</p>
          {s.example_template.subject && (
            <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
              Subject: {s.example_template.subject}
            </p>
          )}
          <pre className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-600 dark:bg-slate-800 dark:text-slate-300">
            {s.example_template.body}
          </pre>
        </div>
      )}
    </div>
  )
}

export default function Tones() {
  const listQ = useQuery({ queryKey: ['tones'], queryFn: tones.list })
  const [selected, setSelected] = useState<number | null>(null)

  const list = listQ.data ?? []
  const active = list.find((t) => t.tone_id === selected) ?? list[0]

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Engage"
        title="Message tones"
        description="Structured tone presets for AI-composed messages. Pick one on an AI compose step to control voice, length, opening style, and what to avoid."
      />

      {listQ.isLoading ? (
        <Card>
          <p className="p-6 text-sm text-slate-400">Loading tones…</p>
        </Card>
      ) : list.length === 0 ? (
        <EmptyState
          icon={Sparkles}
          title="No tones yet"
          description="Tone presets ship as built-ins. If this is empty, the migration that seeds them hasn't run."
        />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          <Card className="p-0">
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {list.map((t) => {
                const isActive = (active?.tone_id ?? null) === t.tone_id
                return (
                  <li key={t.tone_id}>
                    <button
                      type="button"
                      onClick={() => setSelected(t.tone_id)}
                      className={`flex w-full items-center justify-between px-4 py-3 text-left transition ${
                        isActive ? 'bg-brand-50 dark:bg-brand-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                      }`}
                    >
                      <div>
                        <p className="text-sm font-medium text-slate-800 dark:text-slate-100">{t.tone}</p>
                        <p className="text-xs text-slate-400">#{t.tone_id}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {t.is_builtin && <Badge label="Built-in" variant="neutral" />}
                        <ChevronRight className="h-4 w-4 text-slate-300" />
                      </div>
                    </button>
                  </li>
                )
              })}
            </ul>
          </Card>
          <Card>
            <div className="p-6">
              {active && (
                <>
                  <div className="mb-4 flex items-center gap-3">
                    <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{active.tone}</h2>
                    <Badge label={`#${active.tone_id}`} variant="neutral" />
                  </div>
                  <ToneDetail tone={active} />
                </>
              )}
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
