import { cleanup } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, vi } from 'vitest'
import { installFastIntlDateTimeFormatForTests } from './intlDateTimeFormatForTests'

installFastIntlDateTimeFormatForTests()

// Global localStorage / sessionStorage mock for happy-dom environment
const localStore: Record<string, string> = {}
const sessionStore: Record<string, string> = {}

function createStorageMock(store: Record<string, string>) {
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => {
      store[key] = value
    }),
    clear: vi.fn(() => {
      for (const key in store) delete store[key]
    }),
    removeItem: vi.fn((key: string) => {
      delete store[key]
    }),
    length: 0,
    key: vi.fn((index: number) => Object.keys(store)[index] || null),
  }
}

vi.stubGlobal('localStorage', createStorageMock(localStore))
vi.stubGlobal('sessionStorage', createStorageMock(sessionStore))

afterEach(() => {
  cleanup()
})
