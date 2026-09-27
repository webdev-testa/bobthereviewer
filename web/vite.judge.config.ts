import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Judge build — single inlined HTML, no network requests
export default defineConfig({
  plugins: [react(), tailwindcss(), viteSingleFile()],
  resolve: {
    alias: {
      '@': `${import.meta.dirname}/src`,
    },
  },
  define: {
    __JUDGE_MODE__: JSON.stringify(true),
  },
  build: {
    outDir: '../src/bobreviewer/frontend',
    emptyOutDir: false,
    rollupOptions: {
      input: 'index.html',
      output: {
        entryFileNames: 'judge.html',
      },
    },
  },
})
