import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // The empty prefix makes Vite expose *all* variables from frontend/.env and
  // frontend/.env.local, not just VITE_* ones, because this is a dev-server
  // setting that must never be bundled into the browser build.
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env }
  const backend = env.BACKEND_URL || 'http://127.0.0.1:8000'

  return {
    plugins: [react()],
    server: {
      port: Number(env.FRONTEND_PORT) || 5173,
      // The UI talks to the FastAPI backend through this proxy, so the browser
      // only ever makes same-origin requests (no CORS surprises in development).
      proxy: {
        '/api': { target: backend, changeOrigin: true },
      },
    },
    build: { outDir: 'dist', sourcemap: true },
  }
})
