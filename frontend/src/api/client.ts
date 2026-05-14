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
