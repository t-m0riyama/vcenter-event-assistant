import { Component, type ErrorInfo, type ReactNode } from 'react'

/** Recharts / SVG 障害を捕捉し、チャート不具合でアプリ全体が白画面にならないようにする。 */
export class MetricsChartErrorBoundary extends Component<
  { children: ReactNode },
  { hasError: boolean }
> {
  state = { hasError: false }

  /** 子コンポーネントのレンダリング例外を state に反映する。 */
  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true }
  }

  /** 捕捉した例外をコンソールに記録する。 */
  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Metrics chart error:', error, info.componentStack)
  }

  /** 例外時はフォールバック UI、通常時は子要素を描画する。 */
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
