import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Localhost dev proxy is the canonical way to reach the live v2 backend from
// this machine, because the VPS public URL (https://145-223-21-222.sslip.io:8443)
// is blocked by Bitdefender's HTTPS interception on Windows. The proxy goes
// straight at v2's backend HTTP port (:8001) and strips the /api prefix so the
// FastAPI router (which mounts routes at root paths like /auth/login) matches.
// If the VPS gets a real cert + working nginx /api proxy, swap target to that
// and remove the rewrite.

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://145.223.21.222:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
