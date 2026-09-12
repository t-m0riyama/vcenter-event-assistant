import { describe, expect, it } from 'vitest'

import { buildBackendProxyTarget } from './backendProxyTarget'

describe('buildBackendProxyTarget', () => {
  it('uses port 8000 by default', () => {
    expect(buildBackendProxyTarget(undefined)).toBe('http://127.0.0.1:8000')
  })

  it('uses UVICORN_PORT when configured', () => {
    expect(buildBackendProxyTarget('9000')).toBe('http://127.0.0.1:9000')
  })

  it.each(['0', '65536', 'not-a-number', ''])('rejects invalid port %j', (port) => {
    expect(() => buildBackendProxyTarget(port)).toThrow(
      'UVICORN_PORT must be an integer between 1 and 65535',
    )
  })
})
