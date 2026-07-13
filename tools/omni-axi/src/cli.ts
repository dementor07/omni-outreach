#!/usr/bin/env node
/**
 * omni-axi — an agent-ergonomic CLI over omni's public API, built to the AXI
 * standard (https://axi.md). TOON output, pre-computed counts, definitive empty
 * states, structured stdout errors, contextual next-step hints.
 *
 * Home view (no args) is content-first (#8): it prints the tool identity (#10)
 * then live contacts, so an agent can orient and act in one call.
 */

import { fileURLToPath } from "node:url";
import { homedir } from "node:os";
import {
  api,
  ApiError,
  resolveConfig,
  type ClientConfig,
  type Contact,
  type Lead,
} from "./client.js";
import { intFlag, parseArgs } from "./args.js";
import { encodeCount, encodeEmpty, encodeHelp, encodeObject, encodeTable } from "./toon.js";

const DESCRIPTION = "Drive omni's CRM + outbound from the shell — contacts, leads, discovery, enrichment, campaigns.";

// AXI #2: minimal default list schemas (id + a few orienting fields, not every column).
const CONTACT_FIELDS = ["id", "first_name", "last_name", "company", "email"];
const CONTACT_FULL_FIELDS = ["id", "first_name", "last_name", "company", "headline", "email", "linkedin_url", "phone", "source", "created_at"];
const LEAD_FIELDS = ["id", "status", "workflow_id", "updated_at"];

/** stdout is the agent's channel (#6). Everything structured goes here. */
function out(text: string): void {
  process.stdout.write(text + "\n");
}

function binPath(): string {
  const p = process.argv[1] || "omni-axi";
  return p.replace(homedir(), "~");
}

function contactRows(contacts: Contact[], full: boolean): { fields: string[]; rows: Record<string, unknown>[] } {
  const fields = full ? CONTACT_FULL_FIELDS : CONTACT_FIELDS;
  return { fields, rows: contacts as unknown as Record<string, unknown>[] };
}

// ── Commands ──────────────────────────────────────────────────────────────────

async function cmdHome(cfg: ClientConfig): Promise<void> {
  // #10 identity header, then #8 live content.
  out(`bin: ${binPath()}`);
  out(`description: ${DESCRIPTION}`);
  const page = await api.listContacts(cfg, 10, 0);
  if (page.meta.total === 0) {
    out(encodeEmpty("contacts", "contacts in this workspace yet"));
    out(encodeHelp([
      `Run \`omni-axi contacts create --email "<email>"\` to add one`,
      `Run \`omni-axi leads find --input "<who to find>" --connection <name>\` to discover people`,
    ]));
    return;
  }
  const { fields, rows } = contactRows(page.data, false);
  out(encodeCount(page.data.length, page.meta.total));
  out(encodeTable("contacts", fields, rows));
  out(encodeHelp([
    `Run \`omni-axi contacts --limit 50\` for more`,
    `Run \`omni-axi contacts view <id>\` for one contact's full record`,
    `Run \`omni-axi leads\` to see pipeline leads`,
  ]));
}

async function cmdContacts(cfg: ClientConfig, argv: string[]): Promise<void> {
  // Subcommand dispatch: `contacts`, `contacts view <id>`, `contacts create`.
  const sub = argv[0] && !argv[0].startsWith("--") ? argv[0] : null;

  if (sub === "create") {
    const { flags } = parseArgs(argv.slice(1), "contacts create", ["email", "linkedin", "first", "last", "company", "headline", "phone"], []);
    if (!flags.email && !flags.linkedin) {
      throw new ApiError("a contact needs an email or a linkedin url", `example: omni-axi contacts create --email "ada@example.com" --first Ada`, true);
    }
    const created = await api.createContact(cfg, {
      email: flags.email ?? null,
      linkedin_url: flags.linkedin ?? null,
      first_name: flags.first ?? null,
      last_name: flags.last ?? null,
      company: flags.company ?? null,
      headline: flags.headline ?? null,
      phone: flags.phone ?? null,
    });
    out(encodeObject({ contact: "created", id: created.id, email: created.email, name: [created.first_name, created.last_name].filter(Boolean).join(" ") || null }));
    return;
  }

  if (sub === "view") {
    // No single-contact GET on the public API; find it in a bounded page (#3-style detail).
    const id = argv[1];
    if (!id || id.startsWith("--")) throw new ApiError("contacts view needs an id", "example: omni-axi contacts view <id>", true);
    const page = await api.listContacts(cfg, 200, 0);
    const c = page.data.find((x) => x.id === id);
    if (!c) throw new ApiError(`contact ${id} not found in the most recent 200`, "list with `omni-axi contacts --limit 200` to find the id");
    out(encodeObject(c as unknown as Record<string, unknown>));
    return;
  }

  // Default: list (content-first).
  const { flags, bools } = parseArgs(argv, "contacts", ["limit", "offset"], ["full"]);
  const limit = intFlag(flags, "limit", 50, 1, 200);
  const offset = intFlag(flags, "offset", 0, 0, 1_000_000);
  const page = await api.listContacts(cfg, limit, offset);
  if (page.meta.total === 0) {
    out(encodeEmpty("contacts", "contacts in this workspace"));
    out(encodeHelp([`Run \`omni-axi contacts create --email "<email>"\` to add one`]));
    return;
  }
  const { fields, rows } = contactRows(page.data, bools.has("full"));
  out(encodeCount(page.data.length, page.meta.total));
  out(encodeTable("contacts", fields, rows));
  const help = [`Run \`omni-axi contacts view <id>\` for a full record`];
  if (offset + page.data.length < page.meta.total) {
    help.push(`Run \`omni-axi contacts --limit ${limit} --offset ${offset + limit}\` for the next page`);
  }
  out(encodeHelp(help));
}

async function cmdLeads(cfg: ClientConfig, argv: string[]): Promise<void> {
  const sub = argv[0] && !argv[0].startsWith("--") ? argv[0] : null;

  if (sub === "find") {
    const { flags } = parseArgs(argv.slice(1), "leads find", ["input", "connection", "count", "finder"], []);
    if (!flags.input) throw new ApiError("leads find needs --input", `example: omni-axi leads find --input "Heads of Growth at Series-B fintechs" --connection linkfinder`, true);
    if (!flags.connection) throw new ApiError("leads find needs --connection", "example: --connection linkfinder", true);
    const res = await api.findLeads(cfg, {
      finder_type: flags.finder ?? "leads_finder_ai",
      input_data: flags.input,
      connection_name: flags.connection,
      fetch_count: intFlag(flags, "count", 25, 1, 100),
    });
    out(encodeObject({ queued: "leads discovery run", correlation_id: res.correlation_id }));
    out(encodeHelp([`Run \`omni-axi leads\` to see discovered people as they land`]));
    return;
  }

  const { flags } = parseArgs(argv, "leads", ["limit", "offset"], []);
  const limit = intFlag(flags, "limit", 50, 1, 200);
  const offset = intFlag(flags, "offset", 0, 0, 1_000_000);
  const page = await api.listLeads(cfg, limit, offset);
  if (page.meta.total === 0) {
    out(encodeEmpty("leads", "leads in this workspace"));
    out(encodeHelp([`Run \`omni-axi leads find --input "<who>" --connection <name>\` to discover some`]));
    return;
  }
  out(encodeCount(page.data.length, page.meta.total));
  out(encodeTable("leads", LEAD_FIELDS, page.data as unknown as Record<string, unknown>[]));
  const help: string[] = [];
  if (offset + page.data.length < page.meta.total) {
    help.push(`Run \`omni-axi leads --limit ${limit} --offset ${offset + limit}\` for the next page`);
  }
  if (help.length) out(encodeHelp(help));
}

async function cmdEnrich(cfg: ClientConfig, argv: string[]): Promise<void> {
  const { flags } = parseArgs(argv, "enrich", ["email", "linkedin", "source", "connection"], []);
  if (!flags.email && !flags.linkedin) throw new ApiError("enrich needs --email or --linkedin", `example: omni-axi enrich --email ada@example.com --connection apollo`, true);
  if (!flags.connection) throw new ApiError("enrich needs --connection", "example: --connection apollo", true);
  const lead: Record<string, unknown> = {};
  if (flags.email) lead.email = flags.email;
  if (flags.linkedin) lead.linkedin_url = flags.linkedin;
  const res = await api.enrich(cfg, { lead, enrich_source: flags.source ?? "apollo", connection_name: flags.connection });
  out(encodeObject({ queued: "enrichment", correlation_id: res.correlation_id }));
}

async function cmdCampaigns(cfg: ClientConfig, argv: string[]): Promise<void> {
  const sub = argv[0];
  if (sub === "run") {
    const id = argv[1];
    if (!id || id.startsWith("--")) throw new ApiError("campaigns run needs a campaign id", "example: omni-axi campaigns run <id>", true);
    // Campaign ids are UUIDs. Validate the shape at the boundary so an untrusted
    // id can't be steered into path traversal even before encodeURIComponent.
    if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id)) {
      throw new ApiError("campaign id must be a UUID", "example: omni-axi campaigns run 123e4567-e89b-12d3-a456-426614174000", true);
    }
    parseArgs(argv.slice(2), "campaigns run", [], []); // reject stray flags
    const res = await api.runCampaign(cfg, id);
    out(encodeObject({ campaign: "run triggered", ...(res as Record<string, unknown>) }));
    return;
  }
  throw new ApiError("campaigns needs a subcommand", "example: omni-axi campaigns run <id>", true);
}

// ── Help (#10) ────────────────────────────────────────────────────────────────

function topLevelHelp(): string {
  return `bin: ${binPath()}
description: ${DESCRIPTION}

usage: omni-axi [command] [flags]

commands[6]{command,does}:
  (none),Home view — tool identity + recent contacts
  contacts,List contacts; \`create\` to add, \`view <id>\` for one
  leads,List pipeline leads; \`find\` to discover people
  enrich,Queue a one-off enrichment for an email/linkedin
  campaigns run <id>,Trigger a campaign run
  --help,This reference

globals[3]:
  --api-key <key>  (or env OMNI_API_KEY)
  --host <url>     (or env OMNI_API_URL)
  --help           on any command for its flags

Output is TOON (token-efficient). Errors print structured to stdout; exit 0=ok, 1=error, 2=usage.`;
}

// Per-command references (AXI #10: concise, complete, focused on the one command).
const COMMAND_HELP: Record<string, string> = {
  contacts: `omni-axi contacts — list/add/view contacts

  omni-axi contacts [--limit N] [--offset N] [--full]
  omni-axi contacts view <id>
  omni-axi contacts create --email <e> | --linkedin <url> [--first --last --company --headline --phone]`,
  leads: `omni-axi leads — list pipeline leads / discover people

  omni-axi leads [--limit N] [--offset N]
  omni-axi leads find --input "<who to find>" --connection <name> [--count N] [--finder <type>]`,
  enrich: `omni-axi enrich — queue a one-off enrichment

  omni-axi enrich --email <e> | --linkedin <url> --connection <name> [--source apollo]`,
  campaigns: `omni-axi campaigns — run a campaign

  omni-axi campaigns run <campaign-id>`,
};

function printHelp(command?: string): void {
  if (command && COMMAND_HELP[command]) {
    out(COMMAND_HELP[command]);
    return;
  }
  out(topLevelHelp());
}

// ── Entry ─────────────────────────────────────────────────────────────────────

const KNOWN_COMMANDS = new Set(["contacts", "leads", "enrich", "campaigns"]);

async function main(): Promise<number> {
  const argv = process.argv.slice(2);
  const command = argv[0];

  // AXI #6: --help ALWAYS passes, on any command, with NO network call and NO
  // key required. Top-level help, or `<command> --help`, both route here first.
  if (argv.includes("--help")) {
    printHelp(command && KNOWN_COMMANDS.has(command) ? command : undefined);
    return 0;
  }

  // Unknown command must fail as a usage error BEFORE we demand a key (MEDIUM
  // fix: the command-not-found message is more actionable than a key error).
  if (command !== undefined && !KNOWN_COMMANDS.has(command)) {
    out(`error: unknown command \`${command}\``);
    out(encodeHelp(["Run `omni-axi` for the home view", "Run `omni-axi --help` for all commands"]));
    return 2;
  }

  // Config (the API key) is only needed for a real call — resolve it now that we
  // know the command is real and help wasn't requested.
  let cfg: ClientConfig;
  try {
    cfg = resolveConfig(parseGlobalOnly(argv));
  } catch (err) {
    return emitError(err);
  }

  try {
    switch (command) {
      case undefined:
        await cmdHome(cfg);
        break;
      case "contacts":
        await cmdContacts(cfg, argv.slice(1));
        break;
      case "leads":
        await cmdLeads(cfg, argv.slice(1));
        break;
      case "enrich":
        await cmdEnrich(cfg, argv.slice(1));
        break;
      case "campaigns":
        await cmdCampaigns(cfg, argv.slice(1));
        break;
      // command is guaranteed known (validated above) or undefined (home).
    }
  } catch (err) {
    return emitError(err);
  }
  return 0;
}

/** Pull only global flags for early config resolution, ignoring the rest. */
function parseGlobalOnly(argv: string[]): Record<string, string | undefined> {
  const flags: Record<string, string | undefined> = {};
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--api-key" || t === "--host") flags[t.slice(2)] = argv[++i];
    else if (t.startsWith("--api-key=")) flags["api-key"] = t.slice("--api-key=".length);
    else if (t.startsWith("--host=")) flags.host = t.slice("--host=".length);
  }
  return flags;
}

/** AXI #6: structured error on stdout + actionable hint; exit 1 (error) or 2 (usage). */
function emitError(err: unknown): number {
  if (err instanceof ApiError) {
    out(`error: ${err.message}`);
    out(encodeHelp([err.hint]));
    return err.usage ? 2 : 1;
  }
  out(`error: ${err instanceof Error ? err.message : "unexpected failure"}`);
  return 1;
}

// Only run when invoked as the binary (keeps it importable in tests).
if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().then((code) => process.exit(code));
}

export { main };
