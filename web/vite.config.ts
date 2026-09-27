import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// Developer bundle — output goes to src/bobreviewer/frontend/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': `${import.meta.dirname}/src`,
    },
  },
  build: {
    outDir: '../src/bobreviewer/frontend',
    emptyOutDir: true,
  },
})
