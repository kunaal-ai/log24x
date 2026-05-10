import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite' // 1. Add this import

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(), // 2. Add the plugin here
  ],
  server: {
    proxy: {
      '/v1': 'http://localhost:8000',
      // Proxy API paths only — not GET /fraud (that must serve the SPA for client-side routing).
      '/fraud/analyze': 'http://localhost:8000',
      '/fraud/alerts': 'http://localhost:8000',
      '/fraud/stats': 'http://localhost:8000',
    },
  },
})