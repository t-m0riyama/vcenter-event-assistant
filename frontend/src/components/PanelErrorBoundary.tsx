import { Component, type ErrorInfo, type ReactNode } from 'react'

type PanelErrorBoundaryProps = {
  children: ReactNode
  /** フォールバックに表示するパネル名（例: チャット） */
  panelLabel: string
}

type PanelErrorBoundaryState = {
  hasError: boolean
}

/**
 * タブ内パネルのレンダリング例外を捕捉し、アプリ全体の白画面化を防ぐ。
 */
export class PanelErrorBoundary extends Component<
  PanelErrorBoundaryProps,
  PanelErrorBoundaryState
> {
  state: PanelErrorBoundaryState = { hasError: false }

  static getDerivedStateFromError(): PanelErrorBoundaryState {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Panel error (${this.props.panelLabel}):`, error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <p className="hint" role="status">
          {this.props.panelLabel}を表示できませんでした。別のタブに切り替えるか、ページを再読み込みしてください。
        </p>
      )
    }
    return this.props.children
  }
}
