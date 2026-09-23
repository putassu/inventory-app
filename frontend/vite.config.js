import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { env } from 'node:process'

const apiTarget = env.INVENTORY_API_URL || 'http://127.0.0.1:58000'
const apiOrigin = env.INVENTORY_API_ORIGIN || 'http://localhost:18080'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1',
    proxy: {
      '/api/v1': {
        target: apiTarget,
        changeOrigin: true,
        headers: {
          Origin: apiOrigin,
        },
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('origin', apiOrigin)
          })
        },
      },
      '/health': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  test: {
    maxWorkers: 1,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
    globals: true,
  },
})
