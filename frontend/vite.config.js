import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '127.0.0.1',
    proxy: {
      '/api/v1': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
  test: {
    maxWorkers: 2,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/v1/**/*.test.{js,jsx}'],
    globals: true,
  },
})
