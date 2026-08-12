import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { views, type ViewDef } from '../api/v2'
import Button from './Button'
import Card from './Card'
import { useToast } from './Toast'

interface Props {
  viewId: string
  label?: string
  placeholder?: string
  suggestions?: string[]
  onUpdated?: (view: ViewDef) => void
}

export default function ViewPromptBar({
  viewId,
  label = 'Reshape this view',
  placeholder = "Describe the operational view you need…",
  suggestions = [],
  onUpdated,
}: Props) {
  const qc = useQueryClient()
  const toast = useToast()
  const [instruction, setInstruction] = useState('')

  const edit = useMutation({
    mutationFn: (text: string) => views.edit(viewId, text),
    onSuccess: (updated) => {
      qc.setQueryData(['view', viewId], updated)
      qc.setQueryData(['default-view'], updated)
      qc.invalidateQueries({ queryKey: ['view-widget'] })
      qc.invalidateQueries({ queryKey: ['views'] })
      setInstruction('')
      onUpdated?.(updated)
      toast.success('View updated')
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        'Could not apply that view change'
      toast.error(detail)
    },
  })

  const submit = () => {
    const text = instruction.trim()
    if (text.length >= 3 && !edit.isPending) edit.mutate(text)
  }

  return (
    <Card padding="sm" className="overflow-hidden border-brand-200 bg-gradient-to-br from-white via-white to-brand-50/80 dark:border-brand-900/60 dark:from-slate-950 dark:via-slate-950 dark:to-brand-950/25">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div className="flex min-w-[150px] items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand-100 text-brand-700 dark:bg-brand-900/50 dark:text-brand-300"><Sparkles size={16} /></span>
          <div>
            <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-brand-700 dark:text-brand-300">Agent-composable</p>
            <p className="text-sm font-bold text-slate-900 dark:text-white">{label}</p>
          </div>
        </div>
        <input
          value={instruction}
          onChange={(event) => setInstruction(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault()
              submit()
            }
          }}
          placeholder={placeholder}
          className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-800 outline-none transition focus:border-brand-400 focus:ring-2 focus:ring-brand-100 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:focus:ring-brand-950"
        />
        <Button icon={Sparkles} isLoading={edit.isPending} disabled={instruction.trim().length < 3 || edit.isPending} onClick={submit}>
          {edit.isPending ? 'Composing…' : 'Apply view'}
        </Button>
      </div>
      {suggestions.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5 lg:pl-[158px]">
          {suggestions.map((suggestion) => (
            <button key={suggestion} type="button" onClick={() => setInstruction(suggestion)} className="rounded-full border border-slate-200 bg-white/80 px-2.5 py-1 text-[11px] text-slate-500 transition hover:border-brand-300 hover:text-brand-700 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-400">
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </Card>
  )
}
