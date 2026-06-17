// Minimal client-side CSV export. No dependency — RFC-4180 quoting (wrap in
// double-quotes, double any embedded quote) so commas/newlines/quotes in the
// data never corrupt the file. Triggers a browser download of the given rows.

type Cell = string | number | boolean | null | undefined

// UTF-8 byte-order mark, as an escape so the source stays pure-ASCII. Prepended
// to the CSV so Excel reads accented names (e.g. India contacts) correctly.
const BOM = String.fromCharCode(0xfeff)

function escapeCell(value: Cell): string {
  if (value === null || value === undefined) return ''
  const s = String(value)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export interface CsvColumn<T> {
  header: string
  value: (row: T) => Cell
}

/** Build a CSV string from rows + column descriptors. */
export function toCsv<T>(rows: readonly T[], columns: readonly CsvColumn<T>[]): string {
  const head = columns.map((c) => escapeCell(c.header)).join(',')
  const body = rows.map((r) => columns.map((c) => escapeCell(c.value(r))).join(',')).join('\n')
  return body ? `${head}\n${body}` : head
}

/** Build the CSV and trigger a download of `<filename>-<date>.csv`. */
export function downloadCsv<T>(filename: string, rows: readonly T[], columns: readonly CsvColumn<T>[]): void {
  const csv = toCsv(rows, columns)
  const blob = new Blob([BOM + csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}-${new Date().toISOString().slice(0, 10)}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
