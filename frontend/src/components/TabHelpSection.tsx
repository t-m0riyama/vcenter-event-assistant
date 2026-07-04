import type { TabHelpEntry } from '../help/tabHelpContent'
import { HelpIcon } from './help-icon'

type TabHelpSectionProps = {
  entry: TabHelpEntry
}

/** タブに応じた簡易ヘルプと利用者向けガイドへの参照を表示する。 */
export function TabHelpSection({ entry }: TabHelpSectionProps) {
  return (
    <section className="help-section">
      <h2>
        <HelpIcon />
        <span>使い方ガイド</span>
      </h2>
      <p className="help-text">{entry.summary}</p>
      {entry.userGuideDoc ? (
        <p className="help-doc-link">
          詳細な利用者向けガイド:{' '}
          <code className="help-doc-path">{entry.userGuideDoc}</code>
        </p>
      ) : null}
    </section>
  )
}
