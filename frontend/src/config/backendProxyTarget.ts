const DEFAULT_UVICORN_PORT = '8000'

/** Vite 開発サーバーから同じ待受ポートのバックエンドへ接続する。 */
export function buildBackendProxyTarget(uvicornPort: string | undefined): string {
  const port = uvicornPort === undefined ? DEFAULT_UVICORN_PORT : uvicornPort.trim()
  const numericPort = Number(port)
  if (!/^\d+$/.test(port) || numericPort < 1 || numericPort > 65535) {
    throw new Error(`UVICORN_PORT must be an integer between 1 and 65535: ${uvicornPort}`)
  }
  return `http://127.0.0.1:${port}`
}
