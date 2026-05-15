import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'https://srv1575227.hstgr.cloud',
        changeOrigin: true,
      },
    },
  },
})
