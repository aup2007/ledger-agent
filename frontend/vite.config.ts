import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Forward API calls to the FastAPI dev server so the browser sees a single
// origin and CORS is irrelevant during development.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/documents': 'http://localhost:8000',
      '/runs': 'http://localhost:8000',
    },
  },
})
