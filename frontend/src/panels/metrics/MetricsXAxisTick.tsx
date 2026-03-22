import { type ComponentProps } from 'react'
import { Text } from 'recharts'
import type { FormatChartAxisTickOptions } from '../../datetime/formatIsoInTimeZone'
import {
  extractTickAxisValue,
  formatChartAxisTick,
} from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'

/**
 * X 軸目盛り専用。`useTimeZone()` をここで読むことで Recharts の Redux 同期と親のクロージャに依存しない。
 * ラベルは斜め表示し、隣接テキストの重なりを抑える。
 */
export function MetricsXAxisTick(
  props: Record<string, unknown> & {
    readonly tickFill?: string
    readonly tickFormatOptions?: FormatChartAxisTickOptions
  },
) {
  const { timeZone } = useTimeZone()
  const { tickFill, tickFormatOptions, payload, ...rest } = props
  const label = formatChartAxisTick(
    extractTickAxisValue(payload),
    timeZone,
    tickFormatOptions,
  )
  return (
    <Text
      {...(rest as ComponentProps<typeof Text>)}
      fill={tickFill || undefined}
      angle={-40}
      textAnchor="end"
      verticalAnchor="middle"
      dy={6}
    >
      {label}
    </Text>
  )
}
