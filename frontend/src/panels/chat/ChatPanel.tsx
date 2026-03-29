import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost } from '../../api'
import { parseChatResponse, type ChatMessage, type VCenter } from '../../api/schemas'
import { asArray } from '../../utils/asArray'
import { ZonedRangeFields } from '../../datetime/ZonedRangeFields'
import { useTimeZone } from '../../datetime/useTimeZone'
import { resolveEventApiRange } from '../../datetime/graphRange'
import {
  METRICS_DEFAULT_ROLLING_DURATION_MS,
  presetRelativeRangeWallPartsWithUtcFallback,
  zonedRangePartsToCombinedInputs,
  type ZonedRangeParts,
} from '../../datetime/zonedRangeParts'
import { toErrorMessage } from '../../utils/errors'

export function ChatPanel({ onError }: { onError: (e: string | null) => void }) {
  const { timeZone } = useTimeZone()
  const [rangeParts, setRangeParts] = useState<ZonedRangeParts>(() =>
    presetRelativeRangeWallPartsWithUtcFallback(METRICS_DEFAULT_ROLLING_DURATION_MS, 'UTC'),
  )
  const [vcenterId, setVcenterId] = useState<string>('')
  const [vcenters, setVcenters] = useState<VCenter[]>([])
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [includeCpuEventCorrelation, setIncludeCpuEventCorrelation] = useState(false)

  useEffect(() => {
    void (async () => {
      try {
        const raw = await apiGet<unknown>('/api/vcenters')
        setVcenters(asArray<VCenter>(raw))
      } catch (e) {
        onError(toErrorMessage(e))
      }
    })()
  }, [onError])

  const send = useCallback(async () => {
    const text = draft.trim()
    if (!text) return

    const { rangeFromInput, rangeToInput } = zonedRangePartsToCombinedInputs(rangeParts)
    const resolved = resolveEventApiRange(rangeFromInput, rangeToInput, timeZone)
    if (!resolved.ok) {
      onError(resolved.message)
      return
    }
    if (!resolved.from || !resolved.to) {
      onError('期間の開始と終了を指定してください。')
      return
    }

    onError(null)
    const nextMessages: ChatMessage[] = [...messages, { role: 'user', content: text }]
    setMessages(nextMessages)
    setDraft('')
    setLoading(true)
    try {
      const body: Record<string, unknown> = {
        from: resolved.from,
        to: resolved.to,
        messages: nextMessages,
        include_cpu_event_correlation: includeCpuEventCorrelation,
      }
      if (vcenterId) {
        body.vcenter_id = vcenterId
      }
      const raw = await apiPost<unknown>('/api/chat', body)
      const out = parseChatResponse(raw)
      if (out.error) {
        setMessages((m) => [...m, { role: 'assistant', content: `（${out.error}）` }])
      } else {
        setMessages((m) => [...m, { role: 'assistant', content: out.assistant_content }])
      }
    } catch (e) {
      onError(toErrorMessage(e))
      setMessages((m) => m.slice(0, -1))
    } finally {
      setLoading(false)
    }
  }, [draft, messages, onError, rangeParts, timeZone, vcenterId, includeCpuEventCorrelation])

  return (
    <div className="panel chat-panel">
      <p className="hint">
        指定期間のイベント・メトリクス集約を根拠に、質問・追質問ができます（会話はブラウザに保持し、サーバーは保存しません）。
      </p>

      <section className="chat-panel__section" aria-label="集計期間">
        <ZonedRangeFields value={rangeParts} onChange={setRangeParts} />
      </section>

      <section className="chat-panel__section" aria-label="vCenter">
        <label>
          対象 vCenter
          <select
            value={vcenterId}
            onChange={(e) => {
              setVcenterId(e.target.value)
            }}
          >
            <option value="">すべて（登録済み全体の集約）</option>
            {vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="chat-panel__section" aria-label="CPU 近接相関">
        <label className="chat-panel__checkbox-label">
          <input
            type="checkbox"
            checked={includeCpuEventCorrelation}
            onChange={(e) => {
              setIncludeCpuEventCorrelation(e.target.checked)
            }}
            disabled={loading}
          />
          CPU 高負荷とイベントの近接集約を含める（追加 DB クエリあり）
        </label>
      </section>

      <ul className="chat-panel__messages" aria-label="会話">
        {messages.map((m, i) => (
          <li key={`${i}-${m.role}`} className={`chat-panel__msg chat-panel__msg--${m.role}`}>
            <span className="chat-panel__role">{m.role === 'user' ? 'あなた' : 'アシスタント'}</span>
            <div className="chat-panel__bubble">{m.content}</div>
          </li>
        ))}
      </ul>

      <div className="chat-panel__composer">
        <label className="chat-panel__composer-label">
          メッセージ
          <textarea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value)
            }}
            rows={3}
            disabled={loading}
            placeholder="質問を入力…"
          />
        </label>
        <button type="button" className="btn" disabled={loading} onClick={() => void send()}>
          {loading ? '送信中…' : '送信'}
        </button>
      </div>
    </div>
  )
}
