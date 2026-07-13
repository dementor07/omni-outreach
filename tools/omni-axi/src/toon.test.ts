/**
 * TOON encoder tests — the AXI output contract. Run: `npm run build && npm test`.
 * Uses node:test (built-in, no dep) against the compiled dist.
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeCount, encodeEmpty, encodeHelp, encodeObject, encodeTable } from "./toon.js";

test("table: header carries count + fields, rows indented", () => {
  const t = encodeTable("contacts", ["id", "name"], [{ id: "1", name: "Ada" }]);
  assert.equal(t, "contacts[1]{id,name}:\n  1,Ada");
});

test("table: quotes values containing the comma delimiter or a colon", () => {
  const t = encodeTable("x", ["v"], [{ v: "Ada, L." }, { v: "a:b" }]);
  assert.ok(t.includes('"Ada, L."'));
  assert.ok(t.includes('"a:b"'));
});

test("table: null and empty-string are distinguishable", () => {
  const t = encodeTable("x", ["v"], [{ v: null }, { v: "" }]);
  assert.ok(t.includes("null"));
  assert.ok(t.includes('""'));
});

test("empty table keeps the [0] header (definitive, not blank)", () => {
  assert.equal(encodeTable("leads", ["id"], []), "leads[0]{id}:");
});

test("count: omits 'of total' when the page is the whole set", () => {
  assert.equal(encodeCount(5, 5), "count: 5");
  assert.equal(encodeCount(5, 40), "count: 5 of 40 total");
});

test("empty state: states the zero with context (AXI #5)", () => {
  assert.equal(encodeEmpty("contacts", "contacts here"), "contacts: 0 contacts here");
});

test("object: nested objects indent; scalars are typed", () => {
  const o = encodeObject({ id: "x", ok: true, n: 3, missing: null });
  assert.ok(o.includes("ok: true"));
  assert.ok(o.includes("n: 3"));
  assert.ok(o.includes("missing: null"));
});

test("help: empty suggestions produce no block", () => {
  assert.equal(encodeHelp([]), "");
  assert.equal(encodeHelp(["a", "b"]), "help[2]:\n  a\n  b");
});

test("scalar: bare keyword-like strings get quoted so they aren't misread", () => {
  const t = encodeTable("x", ["v"], [{ v: "true" }, { v: "null" }]);
  assert.ok(t.includes('"true"'));
  assert.ok(t.includes('"null"'));
});

test("MEDIUM: object keys with structural chars are quoted (can't corrupt format)", () => {
  const o = encodeObject({ "weird: key, x": "v" });
  assert.ok(o.includes('"weird: key, x": v'));
});

test("MEDIUM: table name and field names with commas are quoted in the header", () => {
  const t = encodeTable("a,b", ["f,g"], [{ "f,g": "1" }]);
  assert.ok(t.startsWith('"a,b"[1]{"f,g"}:'));
});
