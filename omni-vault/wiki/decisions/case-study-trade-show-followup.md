---
title: Case Study — The "Trade Show Follow-up" Campaign
category: decisions
tags: [case-study, product-strategy, UX-failure]
updated: 2026-05-05
---

# Case Study: The "Trade Show Follow-up"

This example illustrates a "standard" business campaign that a human user would expect to build, and explains why **Omni currently fails to deliver it.**

## The Goal
A user just returned from a trade show with 50 names and phone numbers. They want a "High-Touch" follow-up that looks like this:

1. **Intake**: Manually add Name + Phone.
2. **Step 1 (Immediate)**: Send a WhatsApp: "Great meeting you at the show, {{first_name}}!"
3. **Step 2 (Enrichment)**: Use Apollo to find their LinkedIn URL and Email using their name and company.
4. **Step 3 (Branching)**:
   - **If LinkedIn Found**: Send a Connection Request + DM.
   - **If LinkedIn NOT Found**: Send an Email instead.
5. **Step 4 (Urgency)**: If they don't reply within **4 hours**, send an SMS.

---

## Why Omni Fails this User (The "Gaps" in Action)

### Failure A: The "Save" Wall
- **The User Action**: Types Name + Phone into the "Add Lead" modal.
- **The System Response**: `lead_gen.py` rejects the lead because it has no Email or LinkedIn URL.
- **Result**: **The campaign never starts.** The user can't even get past Step 1.

### Failure B: The "Blind" Enrichment
- **The User Action**: Adds an `action_enrich` (Apollo) node.
- **The System Response**: The node only has one output handle ("default").
- **Result**: The user cannot build "Step 3 (Branching)." They have to hope the enrichment worked. If it didn't, the next node (LinkedIn DM) will just fail in the background.

### Failure C: The "Day" Delay
- **The User Action**: Tries to set a "4 Hour" wait for the SMS follow-up.
- **The System Response**: The `delay` node only accepts "Days." 
- **Result**: The user is forced to wait **24 hours** (1 day). The lead goes cold. The urgency of the trade show follow-up is lost.

### Failure D: The "Ghost" Manual Source
- **The User Action**: Goes to "Sources" to see how their 50 trade show leads are performing.
- **The System Response**: The Manual leads don't appear in the Sources tab.
- **Result**: The user can't track the ROI of their trade show effort vs. their other scrapers.

### Failure E: The "Variable" Guesswork
- **The User Action**: Writes the WhatsApp message: "I saw you work at {{company}}."
- **The System Response**: The UI provides no validation or preview.
- **Result**: If the lead data had the company name as "ACME CORP, LLC", the message looks robotic. Without a **Data Transformation** node (e.g., "AI: Clean Company Name"), the user can't send a "human-sounding" message.

---

## Conclusion
This campaign is "simple" to describe but **impossible** to build in the current dashboard. The agents have built a powerful "LinkedIn Scraper Bot," but they haven't built an **Omnichannel Outreach Tool**.

**The fix requires moving beyond "Agentic Automation" and towards "User Orchestration."**
