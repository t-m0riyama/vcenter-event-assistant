import { describe, expect, it } from 'vitest'
import {
  extractTickAxisValue,
  formatChartAxisTick,
  formatChartTooltipLabel,
  formatIsoInTimeZone,
  parseApiUtcInstantMs,
} from './formatIsoInTimeZone'

/**
 * `Intl.DateTimeFormat` の `dateStyle: 'short'` 等はロケールにより **2 桁年**（例: `6/15/25`）になる。
 * 暦年が表れたことを、4 桁年または `M/D/YY` 系の 2 桁年で緩く検証する。
 */
function expectFormattedStringContainsCalendarYear(s: string, fullYear: number): void {
  const four = String(fullYear)
  const two = four.slice(-2)
  const hasFourDigitYear = s.includes(four)
  const hasTwoDigitYearToken = new RegExp(`[/-]${two}([,\\s]|$)`).test(s)
  expect(hasFourDigitYear || hasTwoDigitYearToken).toBe(true)
}

describe('parseApiUtcInstantMs', () => {
  it('treats naive ISO datetime as UTC (matches Z suffix)', () => {
    const naive = '2025-06-15T03:00:05'
    const withZ = '2025-06-15T03:00:05.000Z'
    expect(parseApiUtcInstantMs(naive)).toBe(new Date(withZ).getTime())
  })

  it('passes through explicit Z', () => {
    const s = '2025-06-15T03:00:05.000Z'
    expect(parseApiUtcInstantMs(s)).toBe(new Date(s).getTime())
  })
})

describe('formatIsoInTimeZone', () => {
  it('formats UTC instant in Asia/Tokyo', () => {
    const s = formatIsoInTimeZone('2025-06-15T03:00:00.000Z', 'Asia/Tokyo')
    expectFormattedStringContainsCalendarYear(s, 2025)
    expect(s).toMatch(/12:00/)
  })

  it('naive ISO without Z matches same wall time as explicit UTC for display', () => {
    const naive = formatIsoInTimeZone('2025-06-15T03:00:05', 'Asia/Tokyo', { omitSeconds: true })
    const z = formatIsoInTimeZone('2025-06-15T03:00:05.000Z', 'Asia/Tokyo', { omitSeconds: true })
    expect(naive).toBe(z)
  })

  it('omitSeconds avoids HH:mm:ss on the time axis style output', () => {
    const s = formatIsoInTimeZone('2025-06-15T03:00:05.000Z', 'Asia/Tokyo', {
      omitSeconds: true,
    })
    expect(s).not.toMatch(/\d{1,2}:\d{2}:\d{2}/)
  })

  it('returns em dash for invalid date string', () => {
    expect(formatIsoInTimeZone('not-a-date', 'UTC')).toBe('—')
  })
})

describe('extractTickAxisValue', () => {
  it('returns inner value when payload is a Recharts tick object', () => {
    expect(extractTickAxisValue({ value: 42, coordinate: 0 })).toBe(42)
  })

  it('returns payload when it is already the raw value', () => {
    expect(extractTickAxisValue(42)).toBe(42)
  })
})

describe('formatChartAxisTick', () => {
  const tzTokyo = 'Asia/Tokyo'

  it('フル表示: tick が now より後の暦年（年を付ける）', () => {
    const nowMs = new Date('2024-06-01T00:00:00.000+09:00').getTime()
    const tickMs = new Date('2025-06-15T12:00:00.000+09:00').getTime()
    const s = formatChartAxisTick(tickMs, tzTokyo, { nowMs })
    expectFormattedStringContainsCalendarYear(s, 2025)
  })

  it('同年: 年を省略', () => {
    const nowMs = new Date('2026-03-22T12:00:00.000+09:00').getTime()
    const tickMs = new Date('2026-06-15T10:00:00.000+09:00').getTime()
    const s = formatChartAxisTick(tickMs, tzTokyo, { nowMs })
    expect(s).not.toMatch(/2026/)
  })

  it('昨年かつ今年の同じ月日がまだ未来: 年省略', () => {
    const nowMs = new Date('2026-03-22T12:00:00.000+09:00').getTime()
    const tickMs = new Date('2025-06-15T10:00:00.000+09:00').getTime()
    const s = formatChartAxisTick(tickMs, tzTokyo, { nowMs })
    expect(s).not.toMatch(/2025/)
  })

  it('昨年だが今年の同じ月日は既に過ぎた: 年付き', () => {
    const nowMs = new Date('2026-03-22T12:00:00.000+09:00').getTime()
    const tickMs = new Date('2025-03-10T10:00:00.000+09:00').getTime()
    const s = formatChartAxisTick(tickMs, tzTokyo, { nowMs })
    expectFormattedStringContainsCalendarYear(s, 2025)
  })

  it('2年以上前: 年付き', () => {
    const nowMs = new Date('2026-03-22T12:00:00.000+09:00').getTime()
    const tickMs = new Date('2024-08-01T10:00:00.000+09:00').getTime()
    const s = formatChartAxisTick(tickMs, tzTokyo, { nowMs })
    expectFormattedStringContainsCalendarYear(s, 2024)
  })

  it('Date でも IANA ゾーンで整形（browser の toString ではない）', () => {
    const nowMs = new Date('2024-06-01T00:00:00.000+09:00').getTime()
    const d = new Date('2025-06-15T03:00:00.000Z')
    const s = formatChartAxisTick(d, 'Asia/Tokyo', { nowMs })
    expectFormattedStringContainsCalendarYear(s, 2025)
    expect(s).toMatch(/12:00/)
  })

  it('epoch ms と UTC', () => {
    const nowMs = Date.UTC(2024, 5, 1, 0, 0, 0)
    const ms = new Date('2025-06-15T03:00:00.000Z').getTime()
    const s = formatChartAxisTick(ms, 'UTC', { nowMs })
    expectFormattedStringContainsCalendarYear(s, 2025)
  })

  it('omitMonthDay: 時刻のみ（スラッシュ区切りの日付を含まない）', () => {
    const ms = new Date('2026-06-15T10:30:00.000+09:00').getTime()
    const s = formatChartAxisTick(ms, 'Asia/Tokyo', { omitMonthDay: true })
    expect(s).toMatch(/:/)
    expect(s).not.toMatch(/\//)
  })

  it('omitMonthDay: 無効な timeZone でも日付を含まない（Intl 失敗時は UTC の時分のみ）', () => {
    const ms = new Date('2026-06-15T01:30:00.000Z').getTime()
    const s = formatChartAxisTick(ms, 'Invalid/Timezone', { omitMonthDay: true })
    expect(s).toMatch(/^\d{2}:\d{2} UTC$/)
    expect(s).not.toMatch(/\//)
    expect(s).not.toMatch(/202/)
  })

  it('omitMonthDay: false は従来どおり年付きフル表示になりうる', () => {
    const nowMs = Date.UTC(2024, 5, 1, 0, 0, 0)
    const ms = new Date('2025-06-15T03:00:00.000Z').getTime()
    const s = formatChartAxisTick(ms, 'UTC', { omitMonthDay: false, nowMs })
    expectFormattedStringContainsCalendarYear(s, 2025)
  })
})

describe('formatChartTooltipLabel', () => {
  it('第3引数を省略しても例外にならず formatChartAxisTick に渡せる', () => {
    const ms = new Date('2026-06-15T10:30:00.000+09:00').getTime()
    expect(() => formatChartTooltipLabel(ms, 'Asia/Tokyo')).not.toThrow()
  })

  it('短いレンジ相当でも X 軸の omitMonthDay 時刻のみと違い日付（スラッシュ）を含む', () => {
    const ms = new Date('2026-06-15T10:30:00.000+09:00').getTime()
    expect(formatChartAxisTick(ms, 'Asia/Tokyo', { omitMonthDay: true })).not.toMatch(/\//)
    const tip = formatChartTooltipLabel(ms, 'Asia/Tokyo')
    expect(tip).toMatch(/\//)
    expect(tip).toMatch(/:/)
  })
})
