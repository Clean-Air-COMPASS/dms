import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { version } from './package.json'

const sha = process.env.COMPASSAQ_BUILD_SHA ?? ''
const frontendBuild = {
  application_version: version,
  frontend: {
    commit_sha: /^[0-9a-f]{40}$/.test(sha) ? sha : null,
    build_time_utc: process.env.COMPASSAQ_BUILD_TIME_UTC ?? null,
  },
}


export default defineConfig({
  define: { __FRONTEND_BUILD__: JSON.stringify(frontendBuild) },
  plugins: [react(), tailwindcss(), {
    name: 'frontend-build-identity',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'version.json', source: JSON.stringify(frontendBuild) })
    },
  }],
  server: {
    
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{js,ts,jsx,tsx}'],
  },
})
