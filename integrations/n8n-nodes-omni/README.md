# n8n-nodes-omni

An [n8n](https://n8n.io) community node package for **Omni** — outbound outreach
+ CRM. It wraps the Omni public API (`/public/v1/*`) as first-class n8n
operations and adds an event trigger driven by Omni's outbound webhooks.

Two nodes:

- **Omni** (action) — Contact→Create/List, Campaign→Run, Lead→Enrich/Find/List.
- **Omni Trigger** — starts a workflow when an Omni domain event fires (lead
  replied, invite accepted, campaign run completed, lead enriched, hot lead).
  On activation it registers this workflow's webhook URL as an Omni webhook
  subscription and verifies the `X-Omni-Signature` HMAC on each delivery; on
  deactivation it removes the subscription.

## Install

Community nodes (self-hosted n8n):

1. Settings → Community Nodes → Install.
2. Enter `n8n-nodes-omni`.

Or build locally:

```bash
npm install
npm run build      # tsc + copy icons into dist/
npm run lint       # eslint-plugin-n8n-nodes-base
```

Then link the built package into your n8n custom-nodes directory
(`~/.n8n/custom`) per the n8n community-node docs. **This package is not
published to npm** — the operator publishes it after setting the production
`apiBaseUrl`.

## Credentials — "Omni API"

- **API Base URL** — your Omni control plane API base (default is the current
  box host; the operator sets the real production hostname before publishing).
- **API Key** — an `omni_sk_` key minted in Omni under **Settings → Developer**.

The credential injects `Authorization: Bearer <apiKey>` on every request.

## Verifying deliveries (Omni Trigger)

Each delivery carries `X-Omni-Signature: sha256=<hex hmac>` over the raw JSON
body, keyed by the subscription's signing secret. The trigger verifies this
automatically; if you consume the webhook elsewhere, recompute
`HMAC-SHA256(secret, rawBody)` and constant-time compare.

## License

MIT
