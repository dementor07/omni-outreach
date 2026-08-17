import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Localhost dev proxy is the canonical way to reach the live v2 backend from
// this machine. The current target is the Contabo box's public endpoint, whose
// frontend-container nginx already proxies /api → backend — so we keep the /api
// prefix (no rewrite) and just disable cert verification for the sslip.io host.
// The infra ports on that box are 127.0.0.1-bound, so we can't hit :8001 directly.

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'https://13-140-169-62.sslip.io',
        changeOrigin: true,
        secure: false,
      },
    },
  },
})
