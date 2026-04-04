import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * Rollup が node_modules をまとめすぎると単一チャンクが 500 kB を超え、
 * Vite の既定警告が出る。主要ベンダーを分割して初回ロードと警告の両方を改善する。
 *
 * 上から順に評価する。`recharts` は React に依存するため先に専用チャンクへ振り分ける。
 * いずれにも該当しない依存は `undefined` を返し、Rollup の既定のまとまりに任せる。
 */
function manualChunks(id: string): string | undefined {
  if (!id.includes('node_modules')) return undefined

  if (id.includes('/recharts/')) return 'vendor-recharts'

  if (
    id.includes('/react-dom/') ||
    id.includes('/react/') ||
    id.includes('/scheduler/')
  ) {
    return 'vendor-react'
  }

  if (
    id.includes('/react-markdown/') ||
    id.includes('/remark-') ||
    id.includes('/rehype-') ||
    id.includes('/lowlight/') ||
    id.includes('/highlight.js/')
  ) {
    return 'vendor-markdown'
  }

  return undefined
}

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
})
