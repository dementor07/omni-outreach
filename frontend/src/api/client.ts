import axios from 'axios'

// Same-origin default. The deployed SPA is served by the same nginx that
// proxies /api/* to FastAPI, so `/api` is correct in production. For
// non-prod (sandbox previews, point-at-staging dev), set VITE_API_BASE in
// .env.local — e.g. VITE_API_BASE=https://srv1575227.hstgr.cloud/api.
// Never point this at omnioutreach.space — that domain has no DNS record
// (alias-only in nginx). See omni-vault/wiki/architecture/system-overview.md.
const apiBase = import.meta.env.VITE_API_BASE || '/api'

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
