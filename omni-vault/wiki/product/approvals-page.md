---
title: Approvals Page
category: product
tags: [approvals, human-approval, inbox, sequence, parking]
sources: []
updated: 2026-04-23
---

# Approvals Page

**Route:** `/approvals`
**File:** `frontend/src/pages/Approvals.tsx`
**Backend:** `backend/app/routers/approvals.py`

Omni's human-review inbox. Any lead sitting at a `human_approval` node is parked; this page is where operators approve or reject the lead so it can continue through the sequence.

## When leads land here

The `human_approval` node in the sequence engine does three things:

1. Inserts a row into `approvals` with `status='pending'`, capturing `campaign_id`, `lead_id`, `node_id`, plus `title` and `payload` pulled from the node config.
2. Parks the lead by writing `leads.current_node_id = <this node>`.
3. Does not self-advance. The lead stays parked until the page resolves the approval.

The insert is idempotent per `(lead_id, node_id)` — re-entering a human_approval node never opens a duplicate row while one is still pending.

## Tab filter

Three round-pill buttons backed by `statusFilter: 'pending' | 'approved' | 'rejected'` feed:

```
GET /approvals?status=<filter>&limit=50
```

The backend joins `approvals` to `leads` and `campaigns` so each row ships with `first_name`, `last_name`, `email`, `linkedin_url`, `headline`, `company`, and `campaign_name` already denormalized.

Pending is polled every 15s (`refetchInterval`). Approved/rejected tabs do not poll.

## Row layout

Each approval card shows:

- Campaign name (link to the campaign detail)
- Lead identity (name, email, LinkedIn URL)
- `title` string from the node config
- Optional `payload` preview
- Pending cards: an editable `note` textarea plus **Approve** and **Reject** buttons
- Resolved cards: resolution, resolver, resolved-at timestamp

## Resolution flow

`POST /approvals/{id}/resolve` body: `{ resolution: 'approve' | 'reject', note?: string }`.

The backend:

1. Verifies the approval exists and is still pending — returns `409` otherwise.
2. Sets `status` to `approved` or `rejected`, stores `resolution`, `resolved_by = user_id`, `resolved_at = NOW()`.
3. Calls `sequencer.resume_from_approval(lead_id, approval_id, resolution)`.

`resume_from_approval()` advances the lead through handle `approve` or `reject` and clears `current_node_id`.

## Navigation integration

The sidebar shows an Approvals entry whose badge reads from `GET /approvals/count` (returns `{ pending: <int> }`). The count endpoint is separate from the list endpoint so the badge stays cheap to poll.

## Failure modes

- Resolving an already-resolved approval: backend returns `409 Conflict`. The frontend surfaces a toast and leaves the card in place.
- Resolving an approval whose lead has no `current_node_id`: `resume_from_approval` logs a warning and returns; the approval itself still flips to resolved. This happens if the sequence engine has already unparked the lead by another path (for example a parallel `condition_replied` branch).

## Related Pages

- [[sequence-engine]]
- [[campaigns]]
- [[canvas-editor]]
- [[human-approval-and-reply-intent]]
