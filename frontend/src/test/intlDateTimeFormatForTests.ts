import { vi } from 'vitest'

const NativeDateTimeFormat = Intl.DateTimeFormat

/** `Intl.DateTimeFormat` インスタンスを options キーで共有し、TZ 変換テストの反復を高速化する。 */
const formatterCache = new Map<string, Intl.DateTimeFormat>()

function formatterCacheKey(
  locales: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
): string {
  return JSON.stringify({ locales, options })
}

function getCachedDateTimeFormat(
  locales: Intl.LocalesArgument,
  options?: Intl.DateTimeFormatOptions,
): Intl.DateTimeFormat {
  const key = formatterCacheKey(locales, options)
  const cached = formatterCache.get(key)
  if (cached) return cached
  const fmt = new NativeDateTimeFormat(locales, options)
  formatterCache.set(key, fmt)
  return fmt
}

/**
 * happy-dom 上の Vitest で TZ 反復テストがタイムアウトしないよう、
 * `Intl.DateTimeFormat` をキャッシュ付き実装に差し替える。
 */
export function installFastIntlDateTimeFormatForTests(): void {
  const FastDateTimeFormat = function (
    locales?: Intl.LocalesArgument,
    options?: Intl.DateTimeFormatOptions,
  ): Intl.DateTimeFormat {
    return getCachedDateTimeFormat(locales ?? 'en-US', options)
  } as unknown as typeof Intl.DateTimeFormat

  FastDateTimeFormat.prototype = NativeDateTimeFormat.prototype
  Object.setPrototypeOf(FastDateTimeFormat, NativeDateTimeFormat)

  for (const prop of Object.getOwnPropertyNames(NativeDateTimeFormat)) {
    if (prop === 'length' || prop === 'name' || prop === 'prototype') continue
    const desc = Object.getOwnPropertyDescriptor(NativeDateTimeFormat, prop)
    if (desc) Object.defineProperty(FastDateTimeFormat, prop, desc)
  }

  vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(FastDateTimeFormat)
}
