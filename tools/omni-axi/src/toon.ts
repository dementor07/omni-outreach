/**
 * TOON (Token-Oriented Object Notation) encoder — AXI principle #1.
 *
 * Agents consume this on stdout; it is ~40% cheaper than JSON. We convert to
 * TOON only at the output boundary (internal logic stays JSON), per the AXI
 * skill. Spec: https://toonformat.dev/reference/spec.html
 *
 * Supported shapes (all we need for an AXI CLI):
 *   - tabular array:  `key[N]{f1,f2}:` + indented rows       (encodeTable)
 *   - single object:  `key: value` lines                     (encodeObject)
 *   - help block:     `help[N]:` + indented suggestion lines (encodeHelp)
 *   - definitive empty state (AXI #5)                         (encodeEmpty)
 */

const INDENT = "  ";

/** Quote a scalar iff it contains a delimiter, colon, or structural char (spec §7). */
function scalar(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  const s = String(value);
  if (s === "") return '""';
  // Quote when the value could be misread: commas (delimiter), colons, quotes,
  // leading/trailing space, newlines, or a bare value that looks like a keyword.
  if (/[,:"\n\r\t]/.test(s) || /^\s|\s$/.test(s) || s === "null" || s === "true" || s === "false") {
    const escaped = s
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\r")
      .replace(/\t/g, "\\t");
    return `"${escaped}"`;
  }
  return s;
}

/**
 * Quote an identifier (table name, field name, object key) iff it contains a
 * structural char that would corrupt the header/row grammar. Keys are normally
 * static, but encodeObject is called on API response objects — a free-text key
 * (custom field, tag) must not be able to break the format (review MEDIUM).
 */
function ident(name: string): string {
  if (/[,:{}[\]"\n\r\t]/.test(name) || /^\s|\s$/.test(name) || name === "") {
    return scalar(name);
  }
  return name;
}

/**
 * Encode a uniform array of objects as a TOON table.
 *   items[2]{id,title}:
 *     1,Fix bug
 *     2,Add docs
 */
export function encodeTable(key: string, fields: string[], rows: Array<Record<string, unknown>>): string {
  const header = `${ident(key)}[${rows.length}]{${fields.map(ident).join(",")}}:`;
  if (rows.length === 0) return header;
  const lines = rows.map((row) => INDENT + fields.map((f) => scalar(row[f])).join(","));
  return [header, ...lines].join("\n");
}

/** Encode a single object as `key: value` lines (spec §8). Nested objects recurse. */
export function encodeObject(obj: Record<string, unknown>, depth = 0): string {
  const pad = INDENT.repeat(depth);
  const lines: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v && typeof v === "object" && !Array.isArray(v)) {
      lines.push(`${pad}${ident(k)}:`);
      lines.push(encodeObject(v as Record<string, unknown>, depth + 1));
    } else {
      lines.push(`${pad}${ident(k)}: ${scalar(v)}`);
    }
  }
  return lines.join("\n");
}

/** AXI #9: a `help[N]:` block of next-step suggestions. Empty → omitted by caller. */
export function encodeHelp(suggestions: string[]): string {
  if (suggestions.length === 0) return "";
  const lines = suggestions.map((s) => INDENT + s);
  return [`help[${suggestions.length}]:`, ...lines].join("\n");
}

/** AXI #5: a definitive empty state — states the zero with context. */
export function encodeEmpty(key: string, context: string): string {
  return `${key}: 0 ${context}`;
}

/** AXI #4: the count line — "N of TOTAL total" so agents never re-page to learn size. */
export function encodeCount(shown: number, total: number): string {
  return total === shown ? `count: ${shown}` : `count: ${shown} of ${total} total`;
}
