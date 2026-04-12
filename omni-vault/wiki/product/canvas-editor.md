---
title: Canvas Editor
category: product
tags: [canvas, ReactFlow, xyflow, UX, sequences]
sources: []
updated: 2026-04-12
---

# Canvas Editor

The campaign sequence canvas is the core UX for building outreach sequences. Built with `@xyflow/react`.

## Location

`frontend/src/pages/Campaigns.tsx` — the sequence tab when `campaign.sequence_mode === 'canvas'`

## Node Palette

Draggable from a sidebar palette:
- LinkedIn Invite, LinkedIn DM, WhatsApp, Email, Instagram (stub), Telegram (stub)
- Voice Call
- Branch: Reply? (condition node)
- Wait / Delay

## Custom Edge

`CustomEdge` component — Bezier curve with a ✕ delete button on hover. Clicking deletes the edge via `deleteElements()`.

## Config Sidebar (`ConfigSidebar`)

Right-side panel, opens when a node is selected. Slides in/out. Fields vary by node type:
- All: node type display
- Delay: `delay_days` number input
- Email: account selector + subject + body textarea
- Voice: Standard/Flow toggle + agent selector + (Standard: prompt editor) / (Flow: open editor button)
- Other action nodes: body textarea only

## Serialization

**Critical:** React callbacks (`onChange`, `onDelete`, `onEditTemplate`) are stripped from `node.data` before saving to DB:
```ts
const { onChange, onDelete, onEditTemplate, ...serializableData } = n.data as any
```
This prevents non-serializable functions from being persisted to `sequence_nodes.data JSONB`.

## Save / Load

- Load: `GET /sequences/{campaign_id}` → sets ReactFlow nodes + edges state
- Save: `POST /sequences/save` — deletes all existing nodes/edges for campaign, re-inserts

## Related Pages
- [[sequence-engine]]
- [[voice-node]]
- [[decisions/voice-node-architecture]]
