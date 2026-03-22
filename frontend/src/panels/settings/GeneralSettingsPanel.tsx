import { TimeZoneSelect } from '../../datetime/TimeZoneProvider'
import { useSummaryTopNotableMinScore } from '../../preferences/useSummaryTopNotableMinScore'
import type { ThemePreference } from '../../theme/themeStorage'
import { useTheme } from '../../theme/useTheme'

function ThemeAppearanceSelect() {
  const { preference, setPreference } = useTheme()
  return (
    <label className="tz-select">
      外観
      <select
        value={preference}
        onChange={(e) => setPreference(e.target.value as ThemePreference)}
        aria-label="外観"
      >
        <option value="system">システムに合わせる</option>
        <option value="light">ライト</option>
        <option value="dark">ダーク</option>
      </select>
    </label>
  )
}

export function GeneralSettingsPanel() {
  const { topNotableMinScore, setTopNotableMinScore } = useSummaryTopNotableMinScore()

  return (
    <div className="panel">
      <div className="general-settings-field">
        <p className="hint">
          {
            '概要タブの「要注意イベント（上位）」に表示するイベントの、保存済みスコア（notable_score）の下限です。0 は下限なし（スコア 0 も含む）、1 以上はその値未満を一覧から除外します。0〜100。選択はこのブラウザに保存されます。'
          }
        </p>
        <label className="tz-select">
          要注意イベントの最小スコア
          <input
            type="number"
            min={0}
            max={100}
            step={1}
            value={topNotableMinScore}
            onChange={(e) => {
              const raw = e.target.value
              if (raw === '') {
                return
              }
              const n = Number.parseInt(raw, 10)
              if (Number.isNaN(n)) {
                return
              }
              setTopNotableMinScore(n)
            }}
            aria-label="要注意イベントの最小スコア"
          />
        </label>
      </div>
      <div className="general-settings-field">
        <p className="hint">
          ライト・ダーク、または OS の表示設定に合わせます。選択はこのブラウザに保存されます。
        </p>
        <ThemeAppearanceSelect />
      </div>
      <div className="general-settings-field">
        <p className="hint">
          日時の表示に使うタイムゾーンです。選択はこのブラウザに保存されます。
        </p>
        <TimeZoneSelect />
      </div>
    </div>
  )
}
