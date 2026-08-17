/**
 * Arg-parser tests — locks the review-gate findings (HIGH: swallowing a
 * following flag as a value; LOW: `--flag=` empty value; unknown-flag fail-loud).
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { parseArgs } from "./args.js";
import { ApiError } from "./client.js";

test("both --flag=value and --flag value bind the value", () => {
  const a = parseArgs(["--limit=10"], "x", ["limit"], []);
  assert.equal(a.flags.limit, "10");
  const b = parseArgs(["--limit", "10"], "x", ["limit"], []);
  assert.equal(b.flags.limit, "10");
});

test("HIGH: a value flag followed by another --flag fails loud, never swallows it", () => {
  assert.throws(
    () => parseArgs(["--linkedin", "--api-key", "SECRET"], "contacts create", ["linkedin"], []),
    (e: unknown) => e instanceof ApiError && /needs a value/.test((e as ApiError).message),
  );
});

test("unknown flag is rejected by name with exit-2 usage error", () => {
  assert.throws(
    () => parseArgs(["--stat", "closed"], "contacts", ["limit"], []),
    (e: unknown) => e instanceof ApiError && (e as ApiError).usage === true && /unknown flag --stat/.test((e as ApiError).message),
  );
});

test("LOW: --flag= (explicit empty) parses as empty value, not an unknown flag", () => {
  const a = parseArgs(["--email="], "x", ["email"], []);
  assert.equal(a.flags.email, "");
});

test("bool flags and globals are accepted; positionals collected", () => {
  const a = parseArgs(["view", "abc", "--full", "--help"], "contacts", ["limit"], ["full"]);
  assert.deepEqual(a.positionals, ["view", "abc"]);
  assert.ok(a.bools.has("full"));
  assert.ok(a.bools.has("help"));
});

test("value flag at end with no following token fails loud", () => {
  assert.throws(
    () => parseArgs(["--limit"], "x", ["limit"], []),
    (e: unknown) => e instanceof ApiError && /needs a value/.test((e as ApiError).message),
  );
});
