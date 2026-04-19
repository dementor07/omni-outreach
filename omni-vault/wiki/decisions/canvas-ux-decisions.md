---
title: "ADR: Canvas UX Decisions — April 2026 Overhaul"
category: decisions
tags: [canvas, UX, naming, icons, palette, sequential-builder, lucide-react]
sources: []
updated: 2026-04-19
---

# ADR: Canvas UX Decisions — April 2026 Overhaul

## Status
Accepted — shipped in commits c798e5e → 4d495d3

## Context

The canvas and sequential builder had accumulated several UX problems after being initially built by Gemini:
- The `NodePalette` was a flat list with no category grouping, overflowing its container
- The trigger button was labelled "Genesis Trigger" — opaque, developer-internal language
- The `TriggerNode` card showed "Inception / Lead Accepted" — meaningless to a user
- The save button was labelled "Deploy Canvas" — alarming, implies a production push
- `btn-tactile` was referenced on ~12 buttons but never defined in CSS → invisible errors
- The sequential builder had only 4 add buttons (LinkedIn DM, Email, WhatsApp, Delay)
- Most node icons were placeholder `<Zap>` icons from `lucide-react`
- `TagX` was used but is not exported by the project's installed version of lucide-react

## Decisions

### 1. Node and button naming convention: user intent, not developer implementation

| Old | New | Rationale |
|-----|-----|-----------|
| "Genesis Trigger" | "Sequence Start" | Clear entry-point language; no sci-fi jargon |
| "Inception" / "Lead Accepted" (TriggerNode card) | "Trigger" / "Sequence Start" | Matches the palette button label — one concept, one name |
| "Deploy Canvas" | "Save Canvas" | "Deploy" implies a production release. "Save" is what the user actually does. |

**Rule going forward**: all node labels and button text must use the language a non-technical sales operator would use.

### 2. NodePalette: grouped categories, scrollable

The flat list of 20+ items was unnavigable. Replaced with a 7-group hierarchy:

| Group | Rationale |
|-------|-----------|
| LinkedIn | All LinkedIn-specific actions together |
| Messaging | Cross-channel message sends (email, WhatsApp, SMS, IG, TG) |
| Voice | AI voice call — distinct enough to stand alone |
| Actions | Side-effects without outreach (tags, webhooks) |
| Conditions | Boolean branch gates |
| Events | Async listeners (invite accepted, email opened) |
| Flow | Structural nodes (delay, split, end) |

Panel is `w-52`, `maxHeight: calc(100vh - 160px)`, `overflow-y: auto` — scrollable on small screens.

### 3. Icon semantics: one icon per concept

Every node type now has a semantically correct icon from lucide-react:

| Node type | Icon | Rationale |
|-----------|------|-----------|
| `condition_*` | `GitBranch` | Branching decision tree |
| `split` | `Shuffle` | Randomised A/B routing |
| `event_*` | `Bell` (palette icon or fallback) | Notification/listener |
| `action_add_tag` | `Tag` | Tag |
| `action_remove_tag` | `MinusCircle` | Tag removal (see below) |
| `action_webhook` | `Webhook` | CRM push/integration |
| `action_sms` | `MessageCircle` | Distinct from WhatsApp `MessageSquare` |
| `delay` | `Clock` | Wait/timer |
| `end` | `StopCircle` | Terminal state |

### 4. `TagX` → `MinusCircle` (lucide-react version constraint)

The project's installed lucide-react does **not** export `TagX`. Attempts to use it cause TS2724 build errors on the VPS. `MinusCircle` was chosen as the closest semantic equivalent for "remove tag".

**Decision**: Never introduce a new lucide-react icon without first verifying it exists in the local install (`node -e "const l = require('lucide-react'); console.log(!!l['IconName'])"`).

### 5. `btn-tactile` CSS class

All canvas/builder action buttons reference `btn-tactile` for press feedback. Defined in `frontend/src/index.css` under `@layer components`:
```css
.btn-tactile {
  @apply inline-flex items-center justify-center rounded-xl font-semibold transition-all active:scale-[0.97] disabled:opacity-50 disabled:pointer-events-none;
}
```
Rule: any new button in the canvas panel must use `btn-tactile` in addition to its colour classes.

### 6. Sequential builder: full 12-button grid

Expanded from 4 buttons to 12 (all implementable node types). `condition_*`, `event_*`, and `split` deliberately excluded from the sequential builder because:
- Conditions require True/False branching — linear list can't represent a fork
- Events are async listeners — sequential builder has no graph topology to attach them to
- Split requires two parallel downstream paths

These node types should be greyed out or labelled "Canvas only" in a future iteration if they appear in the sequential context.

## Consequences

- All 23 node types are wired through frontend `NodeType` union, `nodeTypes` map, `NODE_PALETTE`, and `SequentialBuilder` add-buttons where appropriate.
- `action_sms` and `action_webhook` are fully typed and UI-reachable but have no dispatcher handler yet. See [[stubbed-channels-policy]].
- The `Conscious-Drawer-364.md` note that appeared in the vault root during this session is an Obsidian-generated scratch file and should be deleted.

## Related Pages
- [[canvas-editor]]
- [[sequential-builder]]
- [[channels]]
- [[stubbed-channels-policy]]
