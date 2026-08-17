/**
 * Thin API client over omni's public surface (`/public/v1/*`) — the same
 * versioned, API-key-authed endpoints the n8n integration exposes.
 *
 * AXI #6: errors are translated to actionable meaning; raw HTTP/dependency
 * noise never leaks to the agent, and the API key is never echoed.
 */

export interface ClientConfig {
  baseUrl: string;
  apiKey: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly hint: string,
    readonly usage = false, // true → exit code 2 (usage), false → 1 (error)
  ) {
    super(message);
  }
}

/** Resolve config from flags then env. Never prints the key. */
export function resolveConfig(flags: Record<string, string | undefined>): ClientConfig {
  const baseUrl = (flags.host || process.env.OMNI_API_URL || "https://13-140-169-62.sslip.io/api").replace(/\/+$/, "");
  const apiKey = flags["api-key"] || process.env.OMNI_API_KEY || "";
  if (!apiKey) {
    throw new ApiError(
      "no API key configured",
      "set OMNI_API_KEY in the environment, or pass --api-key <key> (create one in Settings → API keys)",
      true,
    );
  }
  return { baseUrl, apiKey };
}

async function request<T>(cfg: ClientConfig, method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${cfg.baseUrl}${path}`, {
      method,
      headers: {
        "X-API-Key": cfg.apiKey,
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    // Network-level failure — translate, never surface the raw fetch error.
    throw new ApiError(
      "could not reach the omni API",
      `check the host is up and reachable: ${cfg.baseUrl}`,
    );
  }
  if (resp.status === 401 || resp.status === 403) {
    throw new ApiError("API key rejected", "verify OMNI_API_KEY is valid and not revoked (Settings → API keys)");
  }
  if (resp.status === 404) {
    throw new ApiError("not found", "check the id or resource path is correct");
  }
  if (!resp.ok) {
    // Extract the server's own detail if present; discard stack/HTML noise.
    let detail = `request failed (HTTP ${resp.status})`;
    try {
      const j = (await resp.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* non-JSON body — keep the generic message */
    }
    throw new ApiError(detail, "adjust the input and retry; run the command with --help for the accepted shape");
  }
  return (await resp.json()) as T;
}

// ── Envelope shapes (from backend/app/routers/public.py) ──────────────────────

export interface Paged<T> {
  data: T[];
  meta: { total: number; limit: number; offset: number };
}

export interface Contact {
  id: string;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  company: string | null;
  headline: string | null;
  linkedin_url: string | null;
  phone: string | null;
  source: string | null;
  created_at: string;
}

export interface Lead {
  id: string;
  contact_id: string | null;
  workflow_id: string | null;
  status: string;
  current_node_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Accepted {
  accepted: boolean;
  correlation_id: string;
}

export const api = {
  listContacts: (cfg: ClientConfig, limit: number, offset: number) =>
    request<Paged<Contact>>(cfg, "GET", `/public/v1/contacts?limit=${limit}&offset=${offset}`),
  createContact: (cfg: ClientConfig, body: Partial<Contact>) =>
    request<Contact>(cfg, "POST", "/public/v1/contacts", body),
  listLeads: (cfg: ClientConfig, limit: number, offset: number) =>
    request<Paged<Lead>>(cfg, "GET", `/public/v1/leads?limit=${limit}&offset=${offset}`),
  findLeads: (cfg: ClientConfig, body: Record<string, unknown>) =>
    request<Accepted>(cfg, "POST", "/public/v1/leads/find", body),
  enrich: (cfg: ClientConfig, body: Record<string, unknown>) =>
    request<Accepted>(cfg, "POST", "/public/v1/enrich", body),
  runCampaign: (cfg: ClientConfig, id: string) =>
    // encodeURIComponent so an untrusted id can't traverse the path or inject a
    // query onto the trusted host with the API key attached (review CRITICAL).
    request<Record<string, unknown>>(cfg, "POST", `/public/v1/campaigns/${encodeURIComponent(id)}/run`),
};
