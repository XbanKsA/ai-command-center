import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    // the same number GitHub gives the APK (1.0.<build>); "1.0.dev" on your PC
    __APP_VERSION__: JSON.stringify(`1.0.${process.env.GITHUB_RUN_NUMBER ?? 'dev'}`),
  },
})