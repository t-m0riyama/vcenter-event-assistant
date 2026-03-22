import { type ComponentProps } from 'react'
import { Text } from 'recharts'
import type { FormatChartAxisTickOptions } from '../../datetime/formatIsoInTimeZone'
import {
  extractTickAxisValue,
  formatChartAxisTick,
} from '../../datetime/formatIsoInTimeZone'
import { useTimeZone } from '../../datetime/useTimeZone'

/** X 軸目盛り専用。`useTimeZone()` をここで読むことで Recharts の Redux 同期と親のクロージャに依存しない。 */
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
    >
      {label}
    </Text>
  )
}
