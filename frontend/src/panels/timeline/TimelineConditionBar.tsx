import { useState } from 'react'

import { ZonedRangeDetails } from '../../datetime/ZonedRangeDetails'
import { formatIsoInTimeZone } from '../../datetime/formatIsoInTimeZone'
import { isValidMetricThresholdPercent } from '../../hooks/periodMetricThresholdDefaults'
import type { useTimelineViewController } from '../../hooks/useTimelineViewController'
import {
  TIMELINE_ROLLING_PRESETS,
  TIMELINE_SOURCE_KINDS,
} from '../../routing/timelineHash'
import { formatPct, KIND_LABELS } from './timelineLabels'
import { anchorWindow } from './timelineModel'

type Controller = ReturnType<typeof useTimelineViewController>

const ANCHOR_WINDOWS = [
  { label: '起点の前後 15 分', halfWidthMs: 15 * 60_000 },
  { label: '起点の前後 1 時間', halfWidthMs: 3_600_000 },
  { label: '起点の前後 6 時間', halfWidthMs: 6 * 3_600_000 },
] as const

/**
 * しきい値（%）の入力欄。入力中は文字列のまま持ち、Enter・フォーカスを外したときに確定する
 * （途中の値で API を呼ばないため）。0〜100 の数値でなければ確定せず、理由を示す。
 */
function ThresholdField({
  id,
  label,
  value,
  onCommit,
}: {
  id: string
  label: string
  value: number
  onCommit: (n: number) => void
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const commit = () => {
    if (draft === null) return
    const n = draft.trim() === '' ? NaN : Number(draft)
    if (!isValidMetricThresholdPercent(n)) {
      setError(`${label.replace('（%）', '')}は 0〜100 の数値で入力してください。`)
      return
    }
    setError(null)
    setDraft(null)
    if (n !== value) onCommit(n)
  }

  return (
    <div className="timeline-bar__threshold">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        min={0}
        max={100}
        step="any"
        className="toolbar__input--short"
        value={draft ?? String(value)}
        aria-invalid={error ? 'true' : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => {
          setDraft(e.target.value)
          setError(null)
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
        }}
      />
      {error ? (
        <p id={`${id}-error`} className="timeline-bar__field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  )
}

/** 条件バー: 期間・起点・vCenter・対象・種別・更新。条件を変えると自動で読み込む。 */
export function TimelineConditionBar({ c }: { c: Controller }) {
  const { conditions, timeZone } = c
  const { range, anchor } = conditions
  // 入力中の文字列。Enter・フォーカスを外したときに確定する（途中の値で API を呼ばないため）
  const [minScoreDraft, setMinScoreDraft] = useState<string | null>(null)
  const minScoreInput = minScoreDraft ?? String(conditions.minScore)

  const commitMinScore = () => {
    if (minScoreDraft === null) return
    const n = Number(minScoreDraft)
    if (minScoreDraft.trim() !== '' && Number.isInteger(n) && n >= 0 && n <= 100 && n !== conditions.minScore) {
      c.setMinScore(n)
    }
    setMinScoreDraft(null)
  }

  const rangeLabel =
    range.mode === 'rolling'
      ? (TIMELINE_ROLLING_PRESETS.find((p) => p.durationMs === range.durationMs)?.label ?? '直近')
      : `${formatIsoInTimeZone(c.resolvedRange.from, timeZone)} ～ ${formatIsoInTimeZone(c.resolvedRange.to, timeZone)}`

  return (
    <section className="timeline-bar" aria-label="タイムラインの条件">
      <div className="timeline-bar__row" role="group" aria-label="期間のプリセット">
        {TIMELINE_ROLLING_PRESETS.map((p) => (
          <button
            key={p.key}
            type="button"
            className={`btn ${range.mode === 'rolling' && range.durationMs === p.durationMs ? 'btn--filled' : 'btn--gray'}`}
            aria-pressed={range.mode === 'rolling' && range.durationMs === p.durationMs}
            onClick={() => c.selectRollingPreset(p.durationMs)}
          >
            {p.label}
          </button>
        ))}
        {anchor ? (
          <>
            <span className="timeline-bar__sep" aria-hidden="true" />
            {ANCHOR_WINDOWS.map((w) => (
              <button
                key={w.label}
                type="button"
                className="btn btn--gray"
                onClick={() => c.setFixedRange(anchorWindow(anchor, w.halfWidthMs))}
              >
                {w.label}
              </button>
            ))}
          </>
        ) : null}
        <button
          type="button"
          className="btn btn--gray timeline-bar__refresh"
          onClick={c.refresh}
          disabled={c.savedView !== null}
          title={c.savedView ? '保存済みの結果を表示中です。現在のデータにするには「現在のデータで再集計」を押してください' : undefined}
          aria-busy={c.loading ? 'true' : 'false'}
        >
          更新
        </button>
      </div>

      {anchor ? (
        <p className="timeline-bar__anchor">
          起点: <strong>{formatIsoInTimeZone(anchor, timeZone)}</strong>{' '}
          <button type="button" className="btn btn--gray" onClick={() => c.setAnchor(null)}>
            起点を解除
          </button>
        </p>
      ) : null}

      <form
        onSubmit={(e) => {
          e.preventDefault()
          c.applyRangeParts()
        }}
      >
        <ZonedRangeDetails
          displayLabel={rangeLabel}
          hint="開始と終了を入力して「適用」（または Enter）を押すと、その期間を固定して読み込みます。時刻は設定のタイムゾーンで入力します。"
          value={c.rangeParts}
          onChange={c.setRangeParts}
          footer={
            <p>
              <button type="submit" className="btn btn--gray">
                適用
              </button>
            </p>
          }
        />
      </form>
      {c.rangeInputError ? (
        <p className="timeline-bar__field-error" role="alert">
          {c.rangeInputError}
        </p>
      ) : null}

      <div className="timeline-bar__filters">
        <label>
          vCenter
          <select value={conditions.vcenterId} onChange={(e) => c.setVcenterId(e.target.value)}>
            <option value="">全て</option>
            {/* 一覧に無い vCenter（削除済み・URL の誤りなど）を「全て」と見せない */}
            {c.vcentersLoaded && conditions.vcenterId && !c.vcenters.some((v) => v.id === conditions.vcenterId) ? (
              <option value={conditions.vcenterId}>不明な vCenter（{conditions.vcenterId.slice(0, 8)}…）</option>
            ) : null}
            {c.vcenters.map((v) => (
              <option key={v.id} value={v.id}>
                {v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="timeline-bar__entity">
          対象（ホスト・VM 名）
          <input
            type="search"
            value={c.entityInput}
            onChange={(e) => c.setEntityInput(e.target.value)}
            placeholder="部分一致"
            autoComplete="off"
          />
        </label>
        <fieldset className="timeline-bar__sources">
          <legend>種別</legend>
          {TIMELINE_SOURCE_KINDS.map((kind) => (
            <label key={kind} className="timeline-bar__check">
              <input
                type="checkbox"
                checked={conditions.sources.includes(kind)}
                disabled={conditions.sources.length === 1 && conditions.sources.includes(kind)}
                onChange={() => c.toggleSource(kind)}
              />
              {KIND_LABELS[kind]}
            </label>
          ))}
        </fieldset>
      </div>

      <details className="toolbar__filters-details">
        <summary className="toolbar__filters-summary">
          <span className="toolbar__filters-summary__title">詳細設定</span>
          <span className="toolbar__filters-summary__preview">
            最小スコア {conditions.minScore}・CPU {formatPct(conditions.cpuThresholdPct)}・メモリ {formatPct(conditions.memoryThresholdPct)}
          </span>
        </summary>
        <p className="hint toolbar__filters-hint">
          イベントはスコアがこの値以上のものだけを一覧に出します（俯瞰グラフの「その他のイベント」には含まれます）。
        </p>
        <label className="timeline-bar__min-score">
          最小スコア
          <input
            type="number"
            inputMode="numeric"
            min={0}
            max={100}
            step={1}
            className="toolbar__input--short"
            value={minScoreInput}
            onChange={(e) => setMinScoreDraft(e.target.value)}
            onBlur={commitMinScore}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitMinScore()
            }}
          />
        </label>
        <p className="hint toolbar__filters-hint">
          メトリクスは、CPU 使用率とメモリ使用率がこの値を超えた区間を出します。ディスクとネットワークは対象外です（値が KB/s で、％のしきい値を当てられないため）。
        </p>
        <div className="timeline-bar__thresholds">
          <ThresholdField
            id="timeline-threshold-cpu"
            label="CPU 使用率のしきい値（%）"
            value={conditions.cpuThresholdPct}
            onCommit={c.setCpuThreshold}
          />
          <ThresholdField
            id="timeline-threshold-memory"
            label="メモリ使用率のしきい値（%）"
            value={conditions.memoryThresholdPct}
            onCommit={c.setMemoryThreshold}
          />
        </div>
      </details>
    </section>
  )
}
