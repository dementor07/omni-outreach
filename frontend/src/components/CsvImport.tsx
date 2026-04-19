import { useCallback, useState } from 'react'
import { Upload, FileText, ArrowRight, Check, X, AlertTriangle } from 'lucide-react'
import { useImportLeads } from '../hooks/useLeads'
import { useToast } from './Toast'

const LEAD_FIELDS = [
  { key: 'linkedin_url', label: 'LinkedIn URL', required: true },
  { key: 'email', label: 'Email' },
  { key: 'first_name', label: 'First Name' },
  { key: 'last_name', label: 'Last Name' },
  { key: 'headline', label: 'Headline' },
  { key: 'company', label: 'Company' },
  { key: 'phone', label: 'Phone' },
  { key: 'source', label: 'Source' },
] as const

interface CsvImportProps {
  campaignId: string
  onComplete: () => void
  onCancel: () => void
}

type Step = 'upload' | 'map' | 'preview' | 'done'

export default function CsvImport({ campaignId, onComplete, onCancel }: CsvImportProps) {
  const [step, setStep] = useState<Step>('upload')
  const [headers, setHeaders] = useState<string[]>([])
  const [rows, setRows] = useState<string[][]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [result, setResult] = useState<{ imported: number; skipped: number } | null>(null)
  const importLeads = useImportLeads()
  const toast = useToast()

  const parseCSV = useCallback((text: string) => {
    const lines = text.split(/\r?\n/).filter((l) => l.trim())
    if (lines.length < 2) return
    const delimiter = lines[0].includes('\t') ? '\t' : ','
    const parsed = lines.map((line) => {
      const result: string[] = []
      let current = ''
      let inQuotes = false
      for (const char of line) {
        if (char === '"') {
          inQuotes = !inQuotes
        } else if (char === delimiter && !inQuotes) {
          result.push(current.trim())
          current = ''
        } else {
          current += char
        }
      }
      result.push(current.trim())
      return result
    })
    const hdrs = parsed[0]
    setHeaders(hdrs)
    setRows(parsed.slice(1))

    // Auto-map by fuzzy match
    const autoMap: Record<string, string> = {}
    for (const field of LEAD_FIELDS) {
      const match = hdrs.find((h) => {
        const norm = h.toLowerCase().replace(/[^a-z]/g, '')
        return norm.includes(field.key.replace(/_/g, '')) || norm === field.key
      })
      if (match) autoMap[field.key] = match
    }
    setMapping(autoMap)
    setStep('map')
  }, [])

  const handleFile = useCallback((file: File) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      if (e.target?.result) parseCSV(e.target.result as string)
    }
    reader.readAsText(file)
  }, [parseCSV])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }, [handleFile])

  const getMappedLeads = useCallback(() => {
    return rows.map((row) => {
      const lead: Record<string, string> = {}
      for (const field of LEAD_FIELDS) {
        const csvCol = mapping[field.key]
        if (csvCol) {
          const idx = headers.indexOf(csvCol)
          if (idx >= 0 && row[idx]) lead[field.key] = row[idx]
        }
      }
      return lead
    }).filter((l) => l.linkedin_url)
  }, [rows, mapping, headers])

  const doImport = useCallback(async () => {
    const leads = getMappedLeads()
    if (!leads.length) { toast.error('No valid leads to import'); return }
    try {
      const res = await importLeads.mutateAsync({ campaignId, leads: leads as any })
      setResult(res)
      setStep('done')
    } catch {
      toast.error('Import failed')
    }
  }, [getMappedLeads, campaignId, importLeads, toast])

  return (
    <div className="space-y-6">
      {/* Step indicator */}
      <div className="flex items-center gap-2 text-xs font-medium text-slate-400">
        {['Upload', 'Map fields', 'Preview', 'Done'].map((label, i) => (
          <span key={label} className="flex items-center gap-2">
            {i > 0 && <ArrowRight size={10} />}
            <span className={step === ['upload', 'map', 'preview', 'done'][i] ? 'text-sky-600' : ''}>
              {label}
            </span>
          </span>
        ))}
      </div>

      {step === 'upload' && (
        <div
          onDrop={handleDrop}
          onDragOver={(e) => e.preventDefault()}
          className="flex flex-col items-center gap-4 rounded-2xl border-2 border-dashed border-slate-300 bg-slate-50 px-8 py-16 transition-colors hover:border-sky-400 hover:bg-sky-50/50"
        >
          <Upload size={32} className="text-slate-400" />
          <p className="text-sm font-medium text-slate-600">Drop a CSV or TSV file here</p>
          <p className="text-xs text-slate-400">or</p>
          <label className="cursor-pointer rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-600">
            Browse files
            <input
              type="file"
              accept=".csv,.tsv,.txt"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
            />
          </label>
        </div>
      )}

      {step === 'map' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            Found <span className="font-semibold text-slate-900">{rows.length}</span> rows and{' '}
            <span className="font-semibold text-slate-900">{headers.length}</span> columns.
            Map CSV columns to lead fields:
          </p>
          <div className="space-y-2">
            {LEAD_FIELDS.map((field) => (
              <div key={field.key} className="flex items-center gap-3">
                <span className="w-32 text-sm text-slate-700">
                  {field.label}
                  {'required' in field && field.required && <span className="text-rose-500">*</span>}
                </span>
                <ArrowRight size={12} className="text-slate-300" />
                <select
                  value={mapping[field.key] || ''}
                  onChange={(e) => setMapping({ ...mapping, [field.key]: e.target.value })}
                  className="flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm outline-none"
                >
                  <option value="">— skip —</option>
                  {headers.map((h) => (
                    <option key={h} value={h}>{h}</option>
                  ))}
                </select>
                {mapping[field.key] && <Check size={14} className="text-emerald-500" />}
              </div>
            ))}
          </div>
          {!mapping.linkedin_url && (
            <div className="flex items-center gap-2 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-700">
              <AlertTriangle size={14} />
              LinkedIn URL mapping is required
            </div>
          )}
          <div className="flex gap-3">
            <button onClick={onCancel} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">Cancel</button>
            <button
              onClick={() => setStep('preview')}
              disabled={!mapping.linkedin_url}
              className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-semibold text-white hover:bg-sky-600 disabled:opacity-40"
            >
              Preview
            </button>
          </div>
        </div>
      )}

      {step === 'preview' && (
        <div className="space-y-4">
          <p className="text-sm text-slate-500">
            Ready to import <span className="font-semibold text-slate-900">{getMappedLeads().length}</span> leads.
            Preview of first 5:
          </p>
          <div className="overflow-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-100 bg-slate-50">
                  {LEAD_FIELDS.filter((f) => mapping[f.key]).map((f) => (
                    <th key={f.key} className="px-3 py-2 text-left text-xs font-medium text-slate-500">{f.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {getMappedLeads().slice(0, 5).map((lead, i) => (
                  <tr key={i} className="border-b border-slate-100">
                    {LEAD_FIELDS.filter((f) => mapping[f.key]).map((f) => (
                      <td key={f.key} className="px-3 py-2 text-slate-700 truncate max-w-[200px]">{(lead as any)[f.key] || '—'}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-3">
            <button onClick={() => setStep('map')} className="rounded-xl border border-slate-200 px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-50">Back</button>
            <button
              onClick={doImport}
              disabled={importLeads.isPending}
              className="rounded-xl bg-emerald-500 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-600 disabled:opacity-60"
            >
              {importLeads.isPending ? 'Importing...' : `Import ${getMappedLeads().length} leads`}
            </button>
          </div>
        </div>
      )}

      {step === 'done' && result && (
        <div className="space-y-4 text-center">
          <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100">
            <Check size={28} className="text-emerald-600" />
          </div>
          <h3 className="text-lg font-semibold text-slate-900">Import complete</h3>
          <p className="text-sm text-slate-500">
            <span className="font-semibold text-emerald-600">{result.imported}</span> imported,{' '}
            <span className="font-semibold text-amber-600">{result.skipped}</span> skipped (duplicates).
          </p>
          <button onClick={onComplete} className="rounded-xl bg-sky-500 px-6 py-2.5 text-sm font-semibold text-white hover:bg-sky-600">
            Done
          </button>
        </div>
      )}
    </div>
  )
}
