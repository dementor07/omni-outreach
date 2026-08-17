---
name: omni-axi
description: >
  Drive omni (CRM + outbound: contacts, leads, people-discovery, enrichment,
  campaigns) from the shell. Use when an agent needs to read or act on omni data
  without the dashboard — list/add contacts, list leads, find people, queue
  enrichment, or run a campaign.
---

# omni-axi

An agent-ergonomic CLI over omni's public API, built to the [AXI](https://axi.md)
standard: output is [TOON](https://toonformat.dev) (≈40% fewer tokens than JSON),
lists carry a total count, empty results are stated explicitly, errors are
structured with a fix, and every output suggests the logical next step.

## Setup

Auth is an omni API key (Settings → API keys). Provide it via env or flag:

```sh
export OMNI_API_KEY="omni_sk_..."
export OMNI_API_URL="https://your-omni-host/api"   # optional; defaults to the hosted box
```

Run without a global install:

```sh
npx -y omni-axi
```

## Commands

Running with **no arguments** prints the tool identity and recent contacts —
enough to orient and act in one call.

```
omni-axi                          # home: identity + recent contacts
omni-axi contacts                 # list contacts (add --full for all fields)
omni-axi contacts --limit 100 --offset 100
omni-axi contacts view <id>       # one contact's full record
omni-axi contacts create --email "ada@example.com" --first Ada --company Engines
omni-axi leads                    # list pipeline leads
omni-axi leads find --input "Heads of Growth at Series-B fintechs" --connection linkfinder
omni-axi enrich --email ada@example.com --connection apollo
omni-axi campaigns run <campaign-id>
```

`--help` on any command lists its flags. Globals (`--api-key`, `--host`, `--help`)
are accepted everywhere.

## Output contract (what an agent can rely on)

- **TOON tables**: `contacts[N]{id,first_name,last_name,company,email}:` then rows.
- **Counts**: `count: 10 of 847 total` — you never have to page just to learn the size.
- **Empty is definitive**: `contacts: 0 contacts in this workspace` (the command succeeded; the zero is the answer).
- **Errors are structured on stdout** with a `help[]` fix; exit codes are `0` ok, `1` error, `2` usage.
- **Next steps**: list/mutation outputs include a `help[]` block of concrete follow-up commands.

## Notes

- `leads find` and `enrich` are asynchronous — they return a `correlation_id`;
  discovered/enriched records appear via `omni-axi leads` / `omni-axi contacts`.
- Reads and writes are scoped to the API key's workspace (enforced server-side by RLS).
