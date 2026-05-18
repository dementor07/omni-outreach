# Node Audit — 2026-05-18

Single source of truth for every node type. Three columns:
- **Frontend renderer** — which React component draws the card
- **ConfigSidebar block** — which form appears when selected
- **Backend handler** — sequencer-side evaluation OR dispatcher-side handler

`MOCK` = renderer exists, no real differentiation
`MISSING` = no implementation
`OK` = component-or-handler is purpose-built and correct

## Action nodes (channel handlers, fire commands to dispatcher)

| Node type | Frontend renderer | ConfigSidebar block | Backend handler | Issues |
|---|---|---|---|---|
| `action_linkedin_invite` | ActionNode (generic, says "Engagement") | Has note + account picker | LinkedInInviteHandler | ❌ generic visual; "Simple/Flow" toggle doesn't apply |
| `action_linkedin_dm` | ActionNode | Template body | LinkedInDMHandler | ❌ generic visual; toggle doesn't apply |
| `action_linkedin_inmail` | ActionNode | Subject + body | LinkedInInMailHandler | ❌ generic visual |
| `action_linkedin_profile_view` | ActionNode | (none?) | LinkedInProfileViewHandler | ❌ no config block; visual same |
| `action_add_tag` | ActionNode | Tag input | AddTagHandler | ❌ shows Simple/Flow which is nonsense |
| `action_remove_tag` | ActionNode | Tag input | RemoveTagHandler | ❌ same as above |
| `action_email` | ActionNode | Email account picker + subject + body | EmailHandler | ❌ generic visual; needs email-shaped card with subject preview |
| `action_whatsapp` | ActionNode | (likely body) | WhatsAppHandler | ❌ generic visual |
| `action_sms` | ActionNode | Body | SMSHandler | ❌ generic visual |
| `action_instagram` | ActionNode | (likely body) | InstagramHandler | ❌ generic visual |
| `action_telegram` | ActionNode | (likely body) | TelegramHandler | ❌ generic visual |
| `action_voice` | ActionNode | Voice agent picker, Simple/Flow IS valid here | VoiceHandler | ⚠️ generic-looking but Simple/Flow toggle IS meaningful for Retell |
| `action_webhook` | ActionNode | URL + method + body template | WebhookHandler | ❌ generic visual |
| `action_enrich` | ActionNode (has found/not_found handles only when isEnrich) | Source selector | EnrichHandler | ✓ branching handles are right; visual still generic |
| `action_data_transform` | ActionNode | Variable name + prompt | DataTransformHandler | ❌ should look like an intelligence node, not engagement |
| `action_ai_compose` | ActionNode | Instruction + channel + tone + max_words + target_variable | AIComposeHandler | ❌ **MOST IMPORTANT** — looks identical to LinkedIn DM, says "Engagement"; should look like an intelligence node with brain icon prominent and the instruction preview visible |
| `action_hot_lead_alert` | ActionNode | Title + body + channel_ids | HotLeadAlertHandler | ❌ should look like an alert/notification node with bell icon, recipient list visible |

## Conditions (branch, never emit a command)

| Node type | Frontend renderer | Backend evaluator |
|---|---|---|
| `condition_replied` | ConditionNode (true/false handles) | sequencer.queue_next_nodes inline | ✓ logic OK, visual generic |
| `condition_linkedin_distance` | ConditionNode | inline | ✓ |
| `condition_tag_exists` | ConditionNode | inline | ✓ |
| `condition_ai_screen` | ConditionNode | inline — calls Claude Haiku via screener | ✓ |
| `condition_lead_source` | ConditionNode | inline — branch by lead.source | ✓ |
| `condition_has_field` | ConditionNode | inline — accepts field/field_name | ✓ (we just fixed key drift) |
| `condition_reply_intent` | ReplyIntentNode (separate) | inline — branches by lead.last_reply_category | ✓ has its own component; this is the model for what other special-purpose nodes should look like |

**Verdict on conditions**: every condition gets the same ConditionNode card. They differ only in title. That's fine for now (low signal-to-noise improvement) UNLESS we add per-condition preview (e.g. "If replied within X days" should show X).

## Control / structural

| Node type | Frontend renderer | Backend |
|---|---|---|
| `delay` | DelayNode | inline — accumulates delta, recurses | ✓ purpose-built |
| `wait_until` | WaitUntilNode | inline | ⚠️ check inline handler exists |
| `split` | SplitNode (with Thompson bandit chip) | inline | ✓ |
| `control_parallel_fork` | ParallelForkNode | inline | ✓ purpose-built |
| `goal` | GoalNode | inline | ✓ |
| `end` | EndNode | inline — terminal | ✓ |
| `human_approval` | HumanApprovalNode (with approve/reject handles) | inline — parks lead, writes to approvals table | ✓ purpose-built |
| `trigger_start` | TriggerNode (sources + live counter) | sequencer.schedule_new_lead entry point | ✓ |

## Events (listeners, park lead until external signal)

| Node type | Frontend renderer | Backend |
|---|---|---|
| `event_invite_accepted` | EventNode | inline — checks lead.accepted_at | ✓ |
| `event_email_opened` | EventNode | inline — checks lead.email_opened_at | ⚠️ need to verify column exists in leads table |
| `event_link_clicked` | EventNode | inline — checks lead.link_clicked_at | ⚠️ same |

## Backend handlers with NO frontend node type

- (none — every dispatcher.registry handler maps to a node type)

## Frontend node types with NO backend handler

- (none confirmed — every node_type the canvas can produce is handled in sequencer or dispatcher)

## The two real visual bugs

1. **AI Compose looks like Engagement** because ActionNode hard-codes the label "Engagement" on line 56 of Nodes.tsx, with the only exception being `isEnrich` which says "Intelligence". Fix: derive the category from the node type, not from a single hardcoded if.

2. **Every action node shows the Simple/Flow toggle** on lines 49-52. It's only meaningful for `action_voice` (Retell flow). Fix: render the toggle only when nodeType === 'action_voice'.

## The two real *architectural* concerns the user raised

1. **"Several kinds of campaigns are not possible"** — needs concrete derivation, will do in Stage 2.
2. **"No agent architecture"** — there's no `action_agent` node, no goal-driven multi-step planner. Stage 3.

## Resolution

Migration 013 + commit batch on 2026-05-18 closed the visual bugs and added the missing node types. See [[parity-gap-analysis-may-2026]] for the gap report, [[architecture-gaps-2026-05-18]] for the architectural-gaps doc, and [[agent-runtime-2026-05-18]] for the agent-runtime decision (Option C, hand-rolled).
