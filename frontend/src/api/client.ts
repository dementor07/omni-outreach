import axios from 'axios'

// Backend base URL. Defaults to "/api" which preserves production behaviour:
// nginx serves the SPA and proxies /api/* to the backend on the internal
// Docker network (same origin, no CORS). The vite dev server proxies the
// same path to localhost:8000 (see vite.config.ts).
//
// Override via VITE_API_BASE in `.env.local` (or the runtime localStorage key
// `omni_api_base`) when pointing a build at a remote backend (preview deploy,
// staging, tunnel). Deployment-specific hostnames live in the deploy docs /
// env, not in source — see omni-vault/wiki/architecture/system-overview.md for
// the canonical host and any server_name aliases to avoid.
//
// Trailing slash is stripped so callers can write `${apiBase}/foo` without
// doubling. Exported so non-axios consumers (e.g. EventSource for SSE) can
// build URLs from the same constant instead of duplicating "/api".
// Initial base URL: check localStorage (user-defined) -> Environment variable -> fallback to "/api"
const getInitialBase = () => {
  const saved = typeof window !== 'undefined' ? localStorage.getItem('omni_api_base') : null
  if (saved) return saved.replace(/\/$/, '')
  return (import.meta.env.VITE_API_BASE ?? '/api').replace(/\/$/, '')
}

export let apiBase = getInitialBase()

export const api = axios.create({
  baseURL: apiBase,
})

/**
 * Dynamically update the API host for the entire application.
 * Persists to localStorage so the "localhost design preview" remains 
 * pointed at the chosen backend across sessions.
 */
export const updateApiBase = (newBase: string) => {
  const cleanBase = newBase.replace(/\/$/, '')
  apiBase = cleanBase
  api.defaults.baseURL = cleanBase
  localStorage.setItem('omni_api_base', cleanBase)
}

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// All mocks removed to allow real API communication in localhost preview.
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
