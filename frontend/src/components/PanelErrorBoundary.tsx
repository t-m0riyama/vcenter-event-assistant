import { Component, useState, type ErrorInfo, type ReactNode } from 'react'

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

  /** 子コンポーネントのレンダリング例外を state に反映する。 */
  static getDerivedStateFromError(): PanelErrorBoundaryState {
    return { hasError: true }
  }

  /** 捕捉した例外をコンソールに記録する。 */
  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`Panel error (${this.props.panelLabel}):`, error, info.componentStack)
  }

  /** 例外時はフォールバック UI、通常時は子要素を描画する。 */
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

export type PanelShellProps = {
  panelLabel: string
  children: (reportError: (message: string | null) => void) => ReactNode
}

/**
 * パネル内の API エラー（``onError`` 経由）とレンダリング例外を 1 箇所で扱う。
 */
export function PanelShell({ panelLabel, children }: PanelShellProps) {
  const [error, setError] = useState<string | null>(null)

  return (
    <PanelErrorBoundary panelLabel={panelLabel}>
      {error ? (
        <div className="error-banner panel-error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {children(setError)}
    </PanelErrorBoundary>
  )
}
