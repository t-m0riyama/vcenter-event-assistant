import type { ReactNode } from 'react'

type SettingsListRowProps = {
  /** 折りたたんだ行の見出し（ルール名など）。 */
  title: ReactNode
  /** 見出しの横に並べるバッジ（`settings-row__badge` の span）。 */
  badges?: ReactNode
  /** 見出しの下に 2 行まで出す要約。 */
  preview?: ReactNode
  /**
   * 折りたたんだ行の読み上げ名（名前やバッジの内容）。開閉の状態は `<details>` が伝えるので、
   * 「折りたたみ」「クリックで展開」などの状態の言葉は入れない（開いた後も同じ名前で読まれるため）。
   */
  ariaLabel: string
  /** 最初から開いておく（追加した直後の行など）。 */
  defaultOpen?: boolean
  /** 展開したときの中身（編集欄と操作）。 */
  children: ReactNode
}

/**
 * 設定タブの一覧の 1 行。見出し・バッジ・要約の行を押すと展開し、中で内容を確認・編集する。
 * `<ul className="settings-list">` の中で使う（イベント種別ガイド・アラート・チャットのサンプルで共通）。
 */
export function SettingsListRow({ title, badges, preview, ariaLabel, defaultOpen, children }: SettingsListRowProps) {
  return (
    <li className="settings-list__item">
      <details className="settings-row" open={defaultOpen || undefined}>
        <summary className="settings-row__summary" aria-label={ariaLabel}>
          <span className="settings-row__disclosure" aria-hidden="true">
            <svg
              className="settings-row__chevron"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <div className="settings-row__summary-inner">
            <div className="settings-row__head">
              <span className="settings-row__title msg">{title}</span>
              {badges}
            </div>
            {preview ? <p className="settings-row__preview">{preview}</p> : null}
          </div>
        </summary>
        <div className="settings-row__body">{children}</div>
      </details>
    </li>
  )
}
