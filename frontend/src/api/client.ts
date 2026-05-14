import axios from 'axios'

// Backend base URL. Defaults to "/api" which preserves production behaviour:
// nginx serves the SPA and proxies /api/* to the backend on the internal
// Docker network (same origin, no CORS). The vite dev server proxies the
// same path to localhost:8000 (see vite.config.ts).
//
// Override via VITE_API_BASE in `.env.local` when pointing a build at a
// remote backend (preview deploy, staging, ngrok tunnel) — canonical
// override is `https://srv1575227.hstgr.cloud/api`. Never point this at
// `omnioutreach.space`: that domain is configured as an nginx server_name
// alias but has no DNS A record (NXDOMAIN). See
// omni-vault/wiki/architecture/system-overview.md.
//
// Trailing slash is stripped so callers can write `${apiBase}/foo` without
// doubling. Exported so non-axios consumers (e.g. EventSource for SSE) can
// build URLs from the same constant instead of duplicating "/api".
export const apiBase = (import.meta.env.VITE_API_BASE ?? '/api').replace(/\/$/, '')

export const api = axios.create({
  baseURL: apiBase,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// MOCK INTERCEPTOR FOR VISUAL PREVIEW
api.interceptors.request.use((config) => {
  const isDemo = config.url?.includes('/campaigns') || config.url?.includes('/sequences') || config.url?.includes('/accounts/voice')
  if (import.meta.env.DEV && isDemo) {
    // If we want to mock specific paths for the editor preview
    if (config.url === '/campaigns' && config.method === 'get') {
      return { ...config, adapter: async () => ({
        data: [{ id: 'demo', name: 'Premium Outreach Campaign', status: 'active', sequence_mode: 'sequential', timezone: 'UTC' }],
        status: 200, statusText: 'OK', headers: {}, config
      })};
    }
    if (config.url?.startsWith('/campaigns/demo') && config.method === 'get') {
       return { ...config, adapter: async () => ({
        data: { id: 'demo', name: 'Premium Outreach Campaign', status: 'active', sequence_mode: 'sequential', timezone: 'UTC' },
        status: 200, statusText: 'OK', headers: {}, config
      })};
    }
    if (config.url?.startsWith('/sequences/demo') && config.method === 'get') {
       return { ...config, adapter: async () => ({
        data: {
          nodes: [
            { id: 'trigger_start', type: 'trigger_start', data: {} },
            { id: 'node_1', type: 'action_linkedin_invite', data: { delay_days: 0 } },
            { id: 'node_2', type: 'delay', data: { delay_days: 1 } },
            { id: 'node_3', type: 'action_email', data: { delay_days: 0 } },
            { id: 'node_4', type: 'action_voice', data: { delay_days: 0 } },
          ],
          edges: [
            { id: 'e1', source: 'trigger_start', target: 'node_1' },
            { id: 'e2', source: 'node_1', target: 'node_2' },
            { id: 'e3', source: 'node_2', target: 'node_3' },
            { id: 'e4', source: 'node_3', target: 'node_4' },
          ]
        },
        status: 200, statusText: 'OK', headers: {}, config
      })};
    }
    if (config.url === '/lead-gen/sources' && config.method === 'get') {
      return { ...config, adapter: async () => ({
        data: [
          { source_type: 'apify_jobs', display_name: 'Job Scraper', description: 'Scrape leads from job boards like LinkedIn, Indeed.', available: true, config_schema: { properties: {} } },
          { source_type: 'apollo', display_name: 'Apollo.io', description: 'Search the Apollo database for targeted B2B leads.', available: true, config_schema: { properties: {} } },
          { source_type: 'proxycurl', display_name: 'Proxycurl', description: 'Enrich LinkedIn profiles with real-time data.', available: true, config_schema: { properties: {} } },
        ],
        status: 200, statusText: 'OK', headers: {}, config
      })};
    }
    if (config.url === '/lead-gen/configs/demo' && config.method === 'get') {
      return { ...config, adapter: async () => ({
        data: [
          { id: 'c1', campaign_id: 'demo', source_type: 'apify_jobs', source_display_name: 'Job Scraper', source_available: true, config: {}, label: 'Software Engineer Scraper', is_enabled: true, cron_schedule: '0 9 * * 1-5', last_run_at: new Date().toISOString(), created_at: new Date().toISOString() },
        ],
        status: 200, statusText: 'OK', headers: {}, config
      })};
    }
  }
  return config
})

api.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)
