import { useState } from 'react'
import { TimeZoneSelect } from '../../datetime/TimeZoneProvider'
import {
  CHAT_MAX_STORED_MESSAGES_MAX,
  CHAT_MAX_STORED_MESSAGES_MIN,
} from '../../preferences/chatMaxStoredMessagesStorage'
import { useAutoRefreshPreferences } from '../../preferences/useAutoRefreshPreferences'
import { useChatMaxStoredMessages } from '../../preferences/useChatMaxStoredMessages'
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
  const { chatMaxStoredMessages, setChatMaxStoredMessages } = useChatMaxStoredMessages()
  const { topNotableMinScore, setTopNotableMinScore } = useSummaryTopNotableMinScore()
  const {
    autoRefreshEnabled,
    setAutoRefreshEnabled,
    autoRefreshIntervalMinutes,
    setAutoRefreshIntervalMinutes,
  } = useAutoRefreshPreferences()
  /**
   * `null` = 未編集（表示は常に `topNotableMinScore` に追従）。
   * 文字列 = フォーカス中のドラフト。親の再レンダーでも上書きされない。
   */
  const [notableScoreDraft, setNotableScoreDraft] = useState<string | null>(null)
  /** 更新間隔（分）の入力ドラフト。 */
  const [intervalDraft, setIntervalDraft] = useState<string | null>(null)
  /** チャット最大保持件数の入力ドラフト。 */
  const [chatMaxDraft, setChatMaxDraft] = useState<string | null>(null)

  const notableScoreDisplay =
    notableScoreDraft !== null ? notableScoreDraft : String(topNotableMinScore)

  const intervalMinutesDisplay =
    intervalDraft !== null ? intervalDraft : String(autoRefreshIntervalMinutes)

  const chatMaxDisplay =
    chatMaxDraft !== null ? chatMaxDraft : String(chatMaxStoredMessages)

  return (
    <div className="panel">
      <div className="general-settings-field">
        <p className="hint">
          チャットタブで保持する会話メッセージの最大件数です。超えた分は古いものから欠落します（FIFO）。0
          は会話を保持しません（送信は可能）。0〜1000。選択はこのブラウザに保存されます。
        </p>
        <label className="tz-select">
          チャットの最大保持件数
          <input
            type="number"
            min={CHAT_MAX_STORED_MESSAGES_MIN}
            max={CHAT_MAX_STORED_MESSAGES_MAX}
            step={1}
            value={chatMaxDisplay}
            onFocus={() => {
              setChatMaxDraft(String(chatMaxStoredMessages))
            }}
            onChange={(e) => {
              setChatMaxDraft(e.target.value)
            }}
            onBlur={(e) => {
              const raw = e.currentTarget.value.trim()
              if (raw === '') {
                setChatMaxDraft(null)
                return
              }
              const n = Number.parseInt(raw, 10)
              if (Number.isNaN(n)) {
                setChatMaxDraft(null)
                return
              }
              setChatMaxStoredMessages(n)
              setChatMaxDraft(null)
            }}
            aria-label="チャットの最大保持件数"
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
            value={notableScoreDisplay}
            onFocus={() => {
              setNotableScoreDraft(String(topNotableMinScore))
            }}
            onChange={(e) => {
              setNotableScoreDraft(e.target.value)
            }}
            onBlur={(e) => {
              const raw = e.currentTarget.value.trim()
              if (raw === '') {
                setNotableScoreDraft(null)
                return
              }
              const n = Number.parseInt(raw, 10)
              if (Number.isNaN(n)) {
                setNotableScoreDraft(null)
                return
              }
              setTopNotableMinScore(n)
              setNotableScoreDraft(null)
            }}
            aria-label="要注意イベントの最小スコア"
          />
        </label>
      </div>
      <div className="general-settings-field">
        <p className="hint">
          概要・イベント・グラフの各タブを表示している間だけ、一定間隔でサーバーから最新データを再取得します。別のタブへ切り替えたあとに戻ったときは、その時点で再読み込みされます。選択はこのブラウザに保存されます。
        </p>
        <label className="tz-select tz-select--inline">
          <input
            type="checkbox"
            checked={autoRefreshEnabled}
            onChange={(e) => setAutoRefreshEnabled(e.target.checked)}
            aria-label="自動更新"
          />
          自動更新
        </label>
      </div>
      <div className="general-settings-field">
        <p className="hint">自動更新の間隔です。1〜300 分。選択はこのブラウザに保存されます。</p>
        <label className="tz-select">
          更新の間隔（分）
          <input
            type="number"
            min={1}
            max={300}
            step={1}
            disabled={!autoRefreshEnabled}
            value={intervalMinutesDisplay}
            onFocus={() => {
              setIntervalDraft(String(autoRefreshIntervalMinutes))
            }}
            onChange={(e) => {
              setIntervalDraft(e.target.value)
            }}
            onBlur={(e) => {
              const raw = e.currentTarget.value.trim()
              if (raw === '') {
                setIntervalDraft(null)
                return
              }
              const n = Number.parseInt(raw, 10)
              if (Number.isNaN(n)) {
                setIntervalDraft(null)
                return
              }
              setAutoRefreshIntervalMinutes(n)
              setIntervalDraft(null)
            }}
            aria-label="更新の間隔（分）"
          />
        </label>
      </div>
    </div>
  )
}
