/**
 * Flag parsing with AXI #6: fail loud on unrecognized flags (exit 2), never
 * silently drop one. A dropped flag is worse than an error — the agent gets
 * plausible output it believes is filtered and proceeds on wrong data.
 */

import { ApiError } from "./client.js";

export interface ParsedArgs {
  positionals: string[];
  flags: Record<string, string | undefined>;
  bools: Set<string>;
}

// Flags allowed on every command (AXI #6: the standardized always-allowed globals).
export const GLOBAL_FLAGS = new Set(["help", "api-key", "host"]);
export const GLOBAL_BOOLS = new Set(["help"]);

/**
 * Parse argv for one command. `valueFlags`/`boolFlags` are the command's OWN
 * known flags; globals are always accepted. An unknown flag throws a usage
 * error listing the valid flags (AXI #6 — self-correcting in one turn).
 */
export function parseArgs(
  argv: string[],
  command: string,
  valueFlags: string[],
  boolFlags: string[],
): ParsedArgs {
  const knownValues = new Set([...valueFlags, ...GLOBAL_FLAGS]);
  const knownBools = new Set([...boolFlags, ...GLOBAL_BOOLS]);
  const positionals: string[] = [];
  const flags: Record<string, string | undefined> = {};
  const bools = new Set<string>();

  for (let i = 0; i < argv.length; i++) {
    const tok = argv[i];
    if (!tok.startsWith("--")) {
      positionals.push(tok);
      continue;
    }
    // Split on the FIRST '=' so `--email=` yields name='email', value='' (LOW fix),
    // and `--email=a@b` yields value 'a@b'.
    const body = tok.slice(2);
    const eq = body.indexOf("=");
    const name = eq === -1 ? body : body.slice(0, eq);
    const inlineValue = eq === -1 ? undefined : body.slice(eq + 1);
    if (knownBools.has(name)) {
      bools.add(name);
      continue;
    }
    if (knownValues.has(name)) {
      let value = inlineValue;
      if (value === undefined) {
        const next = argv[i + 1];
        // HIGH fix: never absorb a following flag token as this flag's value —
        // that silently drops the next flag and feeds garbage to the API. A
        // missing value must fail loud, not swallow `--other`.
        if (next === undefined || next.startsWith("--")) {
          throw new ApiError(`flag --${name} needs a value`, `example: --${name} <value>`, true);
        }
        value = argv[++i];
      }
      flags[name] = value;
      continue;
    }
    // Unknown flag — reject by name, list the valid ones (AXI #6).
    const valid = [...valueFlags, ...boolFlags, ...GLOBAL_FLAGS].map((f) => `--${f}`).join(", ");
    throw new ApiError(
      `unknown flag --${name} for \`${command}\``,
      `valid flags for \`${command}\`: ${valid}`,
      true,
    );
  }
  return { positionals, flags, bools };
}

/** Parse an int flag with a bound, or return the default. Fails loud on garbage. */
export function intFlag(
  flags: Record<string, string | undefined>,
  name: string,
  def: number,
  min: number,
  max: number,
): number {
  const raw = flags[name];
  if (raw === undefined) return def;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < min || n > max) {
    throw new ApiError(`--${name} must be an integer between ${min} and ${max}`, `example: --${name} ${def}`, true);
  }
  return n;
}
