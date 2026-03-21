import { TimeZoneSelect } from '../../datetime/TimeZoneProvider'
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
  return (
    <div className="panel">
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
