import { Component, type ErrorInfo, type ReactNode } from 'react'

/** Catches Recharts/SVG failures so a chart bug does not blank the whole app. */
export class MetricsChartErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Metrics chart error:', error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <p className="hint" role="status">
          チャートを表示できませんでした。再取得するか、ページを再読み込みしてください。
        </p>
      )
    }
    return this.props.children
  }
}
