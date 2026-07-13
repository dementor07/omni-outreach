# omni-axi

An **agent-ergonomic CLI** over omni's public API, built to the [AXI](https://axi.md)
standard (Agent eXperience Interface — the same design language behind `gh-axi`,
`no-mistakes`, and `lavish`). It exists so an agent (yours, or omni's own) can
drive the CRM + outbound engine from the shell with minimal token cost.

## Why AXI, not JSON-over-HTTP

Agents pay tokens per field, per row, per round-trip. This CLI applies the 10 AXI
principles so an agent orients and acts in as few calls as possible:

| # | Principle | Here |
|---|-----------|------|
| 1 | Token-efficient output | TOON on stdout (~40% cheaper than JSON) |
| 2 | Minimal default schemas | 4–5 orienting fields per row; `--full` for all |
| 4 | Pre-computed aggregates | `count: N of TOTAL total` on every list |
| 5 | Definitive empty states | `contacts: 0 contacts in this workspace` |
| 6 | Structured errors + exit codes | errors on stdout with a fix; 0/1/2 exit codes; fail loud on unknown flags |
| 8 | Content-first | no-arg run shows live contacts, not a manual |
| 9 | Contextual disclosure | each output ends with a `help[]` of next steps |
| 10 | Consistent help | `bin:`/`description:` header + per-command `--help` |

## Install & run

```sh
npx -y omni-axi              # no global install
# or
npm i -g omni-axi && omni-axi
```

Auth via `OMNI_API_KEY` (Settings → API keys) and optional `OMNI_API_URL`.

## Develop

```sh
npm install
npm run build     # tsc → dist/
npm test          # node:test TOON contract tests
node dist/cli.js --help
```

Zero runtime dependencies — uses Node 18+ built-in `fetch`. The TOON encoder
(`src/toon.ts`) converts to TOON only at the output boundary; internal logic
stays JSON, per the AXI skill.

## Layout

- `src/toon.ts` — TOON encoder (the AXI output contract)
- `src/client.ts` — typed client over `/public/v1/*`; translates errors, never leaks the key
- `src/args.ts` — flag parser that fails loud on unknown flags (AXI #6)
- `src/cli.ts` — commands, content-first home, help
- `SKILL.md` — the installable Agent Skill (generated from the same guidance the CLI prints)
