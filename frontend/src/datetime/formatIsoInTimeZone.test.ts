import { describe, expect, it } from 'vitest'
import {
  extractTickAxisValue,
  formatChartAxisTick,
  formatIsoInTimeZone,
  parseApiUtcInstantMs,
} from './formatIsoInTimeZone'

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
    expect(s).toMatch(/2025/)
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
    expect(s).toMatch(/2025/)
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
    expect(s).toMatch(/2025/)
  })

  it('2年以上前: 年付き', () => {
    const nowMs = new Date('2026-03-22T12:00:00.000+09:00').getTime()
    const tickMs = new Date('2024-08-01T10:00:00.000+09:00').getTime()
    const s = formatChartAxisTick(tickMs, tzTokyo, { nowMs })
    expect(s).toMatch(/2024/)
  })

  it('Date でも IANA ゾーンで整形（browser の toString ではない）', () => {
    const nowMs = new Date('2024-06-01T00:00:00.000+09:00').getTime()
    const d = new Date('2025-06-15T03:00:00.000Z')
    const s = formatChartAxisTick(d, 'Asia/Tokyo', { nowMs })
    expect(s).toMatch(/2025/)
    expect(s).toMatch(/12:00/)
  })

  it('epoch ms と UTC', () => {
    const nowMs = Date.UTC(2024, 5, 1, 0, 0, 0)
    const ms = new Date('2025-06-15T03:00:00.000Z').getTime()
    const s = formatChartAxisTick(ms, 'UTC', { nowMs })
    expect(s).toMatch(/2025/)
  })

  it('omitMonthDay: 時刻のみ（スラッシュ区切りの日付を含まない）', () => {
    const ms = new Date('2026-06-15T10:30:00.000+09:00').getTime()
    const s = formatChartAxisTick(ms, 'Asia/Tokyo', { omitMonthDay: true })
    expect(s).toMatch(/:/)
    expect(s).not.toMatch(/\//)
  })

  it('omitMonthDay: false は従来どおり年付きフル表示になりうる', () => {
    const nowMs = Date.UTC(2024, 5, 1, 0, 0, 0)
    const ms = new Date('2025-06-15T03:00:00.000Z').getTime()
    const s = formatChartAxisTick(ms, 'UTC', { omitMonthDay: false, nowMs })
    expect(s).toMatch(/2025/)
  })
})
