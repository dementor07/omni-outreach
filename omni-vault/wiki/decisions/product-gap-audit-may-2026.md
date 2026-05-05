---
title: Critical Gap Audit — The User-Impossible Campaign
category: decisions
tags: [UX-debt, audit, product-strategy, failure-modes]
updated: 2026-05-05
---

# Critical Gap Audit: The User-Impossible Campaign

This document identifies core architectural and visual failures where the current implementation serves the **Agent** (Claude/Copilot/Gemini) but renders the product unusable or "broken" for a **Human User**.

## 1. The "Simple Call" Failure (Identity Lockdown)
**Scenario:** A user wants to manually input 10 names and phone numbers to run a simple AI Voice promotion.
- **The Gap:** `backend/app/services/lead_gen.py` (Line 30) hard-rejects leads without a `linkedin_url` or `email`.
- **User Experience:** The "Add Lead" modal in the UI offers a Phone field, but the backend silently discards the lead if the "digital" fields are empty. 
- **Verdict:** **Impossible.** The system is a "LinkedIn/Email scraper" engine that is masquerading as an omnichannel tool.

## 2. The "Concurrent Multi-Channel" Failure
**Scenario:** A user wants to send a LinkedIn DM and an Email *at the same time* to maximize visibility.
- **The Gap:** The `sequencer.py` handles nodes in a linear sequence. There is no "Parallel/Fork" node in the UI or backend logic.
- **User Experience:** The user is forced into a "Waterfall" (LinkedIn THEN Email). They cannot design a "Sync" outreach.
- **Verdict:** **Impossible.** The graph logic is limited to single-path traversal.

## 3. The "Granular Time" Failure (The 'Day' Trap)
**Scenario:** A user wants to wait 2 hours after an invite is accepted before sending a "Welcome" message.
- **The Gap:** The `delay` node logic in `sequencer.py` (Line 73) is hardcoded to `timedelta(days=delay_days)`. 
- **User Experience:** The UI only asks for "Days." A user cannot create high-urgency or real-time follow-ups. In a world of "minutes matter," Omni is stuck in "days matter."
- **Verdict:** **Broken.** Real-time conversion is architecturally blocked.

## 4. The "Human-in-the-Loop AI" Failure
**Scenario:** A user wants the AI to draft a message based on a lead's profile, but wants to **review and edit** that specific draft before it sends.
- **The Gap:** There is no "Draft for Review" state. AI nodes (`action_enrich` or `condition_ai_screen`) are "fire and forget." 
- **User Experience:** The user has no "Drafts" folder. They either trust the AI 100% or they don't use it. The `human_approval` node only allows "Approve/Reject" of a static payload, not a "Live Edit" of an AI-generated draft.
- **Verdict:** **Impossible.** The system lacks an "Intervention" layer for creative work.

## 5. The "Visual Dead-End" (The Trigger Node)
**Scenario:** A user finishes their sequence and wants to "Launch" it for the 500 leads they just imported.
- **The Gap:** The `TriggerNode` on the Canvas is a non-interactive decorative element. 
- **User Experience:** There is no "Run Sequence for Existing Leads" button. The system only triggers on *new* arrivals. 
- **Verdict:** **Broken.** The core "Action" of starting a campaign is missing from the campaign's visual home.

## 6. The "Variable Substitution" Blindness
**Scenario:** A user wants to use `{{company_short_name}}` or `{{recent_post_topic}}` in their messages.
- **The Gap:** The UI only suggests basic fields. If a user types a custom variable, there is no validation to check if that data actually exists on the leads.
- **User Experience:** The user sends 100 messages that say "Hi {{first_name}}, I saw your post about {{err_field_missing}}." 
- **Verdict:** **Fragile.** The system assumes the user is an expert in the underlying JSON schema.

## Summary for Engineering
The agents have built a **Headless State Machine**. They have optimized for **Backend Throughput** and **API Connectivity**. They have completely failed to build a **Product**. 

**Next Steps:**
1. Fix the `RawLead` contract to allow `phone-only` leads.
2. Refactor `delay` nodes to support `unit: minutes|hours|days`.
3. Implement a "Parallel Fork" node in the Canvas.
4. Add a "Drafts" view for Human-AI collaboration.


### Status Update (2026-05-05) - Phase 2 Mitigation
- **Human-in-the-Loop AI**: Implemented an "Edit Draft" feature on the Approvals page. Humans can now modify AI-generated message payloads before clicking "Approve."
