/**
 * チャットの WEB 検索条件（スコープ・積極度）を Settings で編集する。
 */
import {
  type WebSearchAggressiveness,
  type WebSearchScope,
} from '../../preferences/chatWebSearchPrefsStorage'
import { useChatWebSearchPrefs } from '../../preferences/useChatWebSearchPrefs'

const SCOPE_OPTIONS: { value: WebSearchScope; label: string }[] = [
  { value: 'incidents', label: '障害・イベント' },
  { value: 'vsphere_ops', label: 'vSphere 運用全般' },
  { value: 'vmware_ecosystem', label: 'VMware 関連製品まで' },
]

const AGGRESSIVENESS_OPTIONS: { value: WebSearchAggressiveness; label: string }[] = [
  { value: 'conservative', label: '必要なときだけ' },
  { value: 'balanced', label: 'バランス' },
  { value: 'aggressive', label: '積極的に検索' },
]

/** WEB 検索条件設定パネル。 */
export function ChatWebSearchPrefsPanel() {
  const { prefs, setPrefs } = useChatWebSearchPrefs()

  return (
    <div className="panel">
      <h2>WEB 検索の条件</h2>
      <p className="hint">
        入力欄の「WEB 検索を許可」が ON のときに適用されます。保存先はこのブラウザの
        localStorage です。
      </p>
      <div className="form-grid">
        <label>
          検索スコープ
          <select
            aria-label="検索スコープ"
            value={prefs.scope}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                scope: e.target.value as WebSearchScope,
              })
            }
          >
            {SCOPE_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          検索の積極度
          <select
            aria-label="検索の積極度"
            value={prefs.aggressiveness}
            onChange={(e) =>
              setPrefs({
                ...prefs,
                aggressiveness: e.target.value as WebSearchAggressiveness,
              })
            }
          >
            {AGGRESSIVENESS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  )
}
