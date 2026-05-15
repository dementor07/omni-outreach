---
title: Canvas + Campaign-detail redesign · rose brand
category: decisions
tags: [canvas, campaigns, design-system, brand]
date: 2026-05-15
related: [[omni-api-naming]], [[mandate-frontend-refactor]], [[canvas-ux-decisions]]
---

# Canvas + Campaign-detail redesign · rose brand

## Decision

1. **Brand palette is rose.** `brand.50→900` in `tailwind.config.ts` now maps to Tailwind's stock rose ramp (`#fff1f2 → #881337`). Every `bg-brand-*` / `text-brand-*` / `ring-brand-*` token resolves to rose from `95ffbe4` forward.
2. **Campaigns detail and the canvas now compose the established primitives** (Card, CardHeader, Button, Badge, Tabs, PageHeader) — no more raw-div panel chrome, no more slate-900 "tactile" buttons, no more uppercase-tracking-[0.2em] cramped headings inside the design system.

Commits: `95ffbe4` (palette), `c966c64` (Campaigns + canvas).

## Why rose

User-driven. The sky brand worked but didn't differentiate. Rose:
- Reads as a high-energy "outreach" hue — appropriate for an outbound marketing platform.
- Sits adjacent to the design-system's status palette (`success=emerald`, `warning=amber`, `danger=rose`) without colliding — `danger` and `brand` overlap conceptually only when an action *is* destructive, which is fine.
- Already documented as a swatch ramp in the style-guide page, so the page now reads correctly the moment the brand swatch is rose.

## What changed in Campaigns/detail

| Surface | Before | After |
|---|---|---|
| Status meta-row | Anemic single-line: `Badge | timezone-text | (maybe Simulation)` | Structured strip: `Badge → Launch / Resume-Pause segmented → divider → TZ label → optional Simulation chip`. Each separator is a 12px-tall `bg-slate-200` hairline, not a literal `\|` glyph. |
| Resume/Pause | Icon-only segmented control | Explicit "Resume" / "Pause" copy with emerald/amber status palette. |
| Clone/Delete | `size="md"` outweighed the meta strip | `size="sm"`. |
| Panel containers (leads/queue/sources/settings) | Raw `<div className="rounded-2xl border ...">` with inconsistent shadows | All four use `<Card padding="lg">`. Single source of truth for surface chrome, dark-mode classes ride along. |
| Section headings | `text-lg font-semibold uppercase tracking-tight` | `text-[15px] font-semibold` shared with CardHeader, plus a description line. |
| Leads pipeline buttons | `btn-tactile` raw markup | Design-system `<Button>` primitives. Import is now `variant="primary"` (it's the lead action); Export drops to secondary. |

## What changed in the canvas

| Surface | Before | After |
|---|---|---|
| Background grid | `#cbd5e1` washed-out dot pattern | `#e2e8f0` with `gap=24 size=1.4` — clearer pattern, less competing with edges. |
| Controls + MiniMap chrome | Floating shadows, inconsistent radius | `rounded-xl border bg-white` + dark-mode classes. MiniMap node fills `#fb7185` (brand-400), 4%-opacity mask. |
| Undo/Redo cluster | Heavy `rounded-2xl shadow-xl p-1` chip | Slim `border-slate-200 bg-white/90 backdrop-blur` segmented control. |
| Save Sequence | `bg-slate-900 px-5 py-2.5 uppercase tracking-widest` block | Design-system `<Button variant="primary" size="sm" icon={Save} isLoading={...} />`. |
| Node selection ring | Hardcoded `border-sky-500 ring-sky-500/10` (12 occurrences) | `border-brand-500 ring-brand-500/10` — selection now reads as the brand, not as a sky accent fighting per-node colors. |
| ActionNode "Nested Architecture" chip | sky-200/sky-50/sky-500/sky-600 hardcodes | Neutral slate with dark-mode classes — reads as a structural badge, not an accidental brand callout. |

## What changed in NodeSelector

Full rewrite. The prior selector had:
- A slate-900 brutalist "Sequence Start" CTA at the top
- `text-[10px] font-black uppercase tracking-[0.2em]` group labels that took horizontal space
- Uppercase tracking-[0.18em] sub-group dividers
- 5×5px scrollbar hidden behind `scrollbar-hide`
- 52px-wide column that truncated several node labels

New design:
- Header bar (`Add module` + `+` glyph) sits above a bordered Trigger CTA (rose primary, matching the design-system button)
- Group labels are `text-[9px] font-semibold uppercase tracking-[0.18em] text-slate-400` — visible hierarchy without shouting
- Each node item is `text-[12px] font-medium` with a 20×20 icon well that takes its color from `NODE_PALETTE` (`p.bg` + `p.color`)
- 56px wide so longer labels fit without truncation
- Max height `calc(100vh-180px)` clears the topbar + tab nav + page header

## Anti-Slop check

| Rule | Status |
|---|---|
| 1 · no dead code | ✅ Every primitive consumed in the same commit. |
| 2 · no mega-components | ✅ `index.tsx` redesign was in-place; NodeSelector was a clean rewrite, still 74 lines. |
| 3 · high-signal variables | ✅ `NODE_PALETTE` already drives the per-node accent colors; nothing new added. |
| 4 · "Ready" means human-verified | Gated on the chrome-devtools-mcp post-deploy screenshot (next step). |
| 5 · errors first-class | No new error paths. Existing `Button.isLoading` covers the Save spinner. |

## Open follow-ups

- `NODE_PALETTE` (`constants.tsx`) still hardcodes per-node accent colors (sky, indigo, etc. for action nodes). These are intentional channel-specific colors, not brand — leaving them. Consider whether channels with no natural color (Webhook, Set Variable, Add Tag) should drop to slate to reduce visual noise.
- `wait_until` / `goal` / `end` nodes use orange / emerald / rose backgrounds respectively. They're conceptually "control flow," might be cleaner if they shared a single muted background and used icon/text to convey type. Out of scope this pass.
- Dark mode on the canvas hasn't been visually verified end-to-end. The classes are present; needs a Chrome devtools toggle.
