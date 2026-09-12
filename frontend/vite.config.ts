import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

import { buildBackendProxyTarget } from './src/config/backendProxyTarget'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.join(__dirname, '..')

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

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, 'UVICORN_')
  const backendTarget = buildBackendProxyTarget(env.UVICORN_PORT)

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target: backendTarget, changeOrigin: true },
        '/health': { target: backendTarget, changeOrigin: true },
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks,
        },
      },
    },
  }
})
