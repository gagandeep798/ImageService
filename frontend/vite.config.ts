import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '^/(auth|images|users|health)': { target: env.VITE_SAM_LOCAL_API_URL, changeOrigin: true },
      },
    },
    build: { outDir: 'dist', sourcemap: false },
  }
})
