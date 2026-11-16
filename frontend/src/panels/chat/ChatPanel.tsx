import './ChatPanel.css'

import { useChatSamplePrompts } from '../../preferences/useChatSamplePrompts'
import { ChatContextBar } from './ChatContextBar'
import { ChatInputBar } from './ChatInputBar'
import { ChatMessagesList } from './ChatMessagesList'
import { ChatPromptPreviewModal } from './ChatPromptPreviewModal'
import type { ChatHandoffInput } from '../../hooks/chatHandoff'
import { useChatPanelController } from '../../hooks/useChatPanelController'

/**
 * 期間集約コンテキスト付きの LLM チャットパネル。会話リストは最下部付近にいるときだけ追従し、
 * アシスタント応答後はそのメッセージ先頭が見える位置へ、ユーザーのみ末尾のときはリスト最下端へ寄せる。
 * 送信中はリスト末尾にプレースホルダ行を出し、`aria-busy` で状態を示す。
 * サンプル質問はチップをクリックすると textarea 末尾へ即時追記する（送信はしない。`ChatSamplePromptsProvider` 必須）。
 */
export function ChatPanel({
  onError,
  handoff = null,
  onHandoffApplied,
}: {
  onError: (e: string | null) => void
  /** タイムラインから引き継いだ期間・vCenter。`nonce` が変わるたびに、期間と vCenter だけを差し替える。 */
  handoff?: ChatHandoffInput | null
  /** 引き継ぎを適用したら呼ぶ（呼び出し側が引き継ぎを消し、作り直しのときに当て直さない）。 */
  onHandoffApplied?: () => void
}) {
  const { visibleChatSamplePrompts } = useChatSamplePrompts()
  const c = useChatPanelController(onError, handoff, onHandoffApplied)

  return (
    <div className="panel chat-panel">
      <ChatContextBar
        rangeParts={c.rangeParts}
        setRangeParts={c.setRangeParts}
        applyRollingPreset={c.applyRollingPreset}
        rangeDisplayLabel={c.rangeDisplayLabel}
        vcenters={c.vcenters}
        vcenterId={c.vcenterId}
        setVcenterId={c.setVcenterId}
        loading={c.loading}
        includePeriodMetricsCpu={c.includePeriodMetricsCpu}
        setIncludePeriodMetricsCpu={c.setIncludePeriodMetricsCpu}
        includePeriodMetricsMemory={c.includePeriodMetricsMemory}
        setIncludePeriodMetricsMemory={c.setIncludePeriodMetricsMemory}
        includePeriodMetricsDiskIo={c.includePeriodMetricsDiskIo}
        setIncludePeriodMetricsDiskIo={c.setIncludePeriodMetricsDiskIo}
        includePeriodMetricsNetworkIo={c.includePeriodMetricsNetworkIo}
        setIncludePeriodMetricsNetworkIo={c.setIncludePeriodMetricsNetworkIo}
        metricThresholdCpuInput={c.metricThresholdCpuInput}
        metricThresholdCpuPct={c.metricThresholdCpuPct}
        setMetricThresholdCpuInput={c.setMetricThresholdCpuInput}
        setMetricThresholdCpuPct={c.setMetricThresholdCpuPct}
        metricThresholdMemoryInput={c.metricThresholdMemoryInput}
        metricThresholdMemoryPct={c.metricThresholdMemoryPct}
        setMetricThresholdMemoryInput={c.setMetricThresholdMemoryInput}
        setMetricThresholdMemoryPct={c.setMetricThresholdMemoryPct}
        metricThresholdDiskInput={c.metricThresholdDiskInput}
        metricThresholdDiskPct={c.metricThresholdDiskPct}
        setMetricThresholdDiskInput={c.setMetricThresholdDiskInput}
        setMetricThresholdDiskPct={c.setMetricThresholdDiskPct}
        metricThresholdNetworkInput={c.metricThresholdNetworkInput}
        metricThresholdNetworkPct={c.metricThresholdNetworkPct}
        setMetricThresholdNetworkInput={c.setMetricThresholdNetworkInput}
        setMetricThresholdNetworkPct={c.setMetricThresholdNetworkPct}
        onMetricThresholdInputChange={c.handleMetricThresholdInputChange}
      />

      {c.handoffNote && (
        <div className="hint chat-panel__handoff-note" role="note" aria-label="タイムラインからの引き継ぎ">
          <p>タイムラインの期間と vCenter を引き継ぎました。</p>
          <p>
            絞り込み（対象・種別・起点・最小スコア・しきい値）は引き継がれません。
            {c.handoffNote.narrowedBy.length > 0
              ? `タイムラインで絞っていた${c.handoffNote.narrowedBy.join('・')}は、チャットの集計に反映されていません。`
              : null}
          </p>
          {c.handoffNote.fromSavedSnapshot && (
            <p>
              保存済みのスナップショットを表示中でしたが、チャットは現在のデータで集計します。元のデータが保持期間を過ぎていると、内容が少ないか空になります。
            </p>
          )}
          {c.handoffNote.hadConversation && <p>以前の会話は前の期間のものです。</p>}
          <button type="button" className="btn btn--gray" onClick={c.dismissHandoffNote}>
            閉じる
          </button>
        </div>
      )}

      <ChatMessagesList
        messages={c.messages}
        loading={c.loading}
        timeZone={c.timeZone}
        onCopyAssistantMessage={c.copyAssistantMessageContent}
        pendingLabel={
          c.webSearchAvailable && c.enableWebSearch
            ? 'WEB 調査を含む応答を生成しています…'
            : undefined
        }
      />

      {c.lastLlmContext != null && (
        <p className="hint chat-panel__llm-meta" role="status" aria-live="polite">
          LLM 入力（目安）: 推定 {c.lastLlmContext.estimated_input_tokens} / {c.lastLlmContext.max_input_tokens}{' '}
          トークン
          {c.lastLlmContext.json_truncated ? '・JSON 切り詰めあり' : '・JSON 切り詰めなし'}
          ・会話 {c.lastLlmContext.message_turns} ターン（トリム後）
        </p>
      )}

      {!c.canSend && (
        <p className="hint" role="status">
          セッションを識別できないため、チャットの保存・送信・プレビューは利用できません。
        </p>
      )}
      <ChatInputBar
        canSend={c.canSend}
        loading={c.loading}
        previewing={c.previewing}
        hasMessages={c.messages.length > 0}
        visibleChatSamplePrompts={visibleChatSamplePrompts}
        draft={c.draft}
        setDraft={c.setDraft}
        draftTextareaRef={c.draftTextareaRef}
        onClearConversation={c.handleClearConversation}
        onSend={c.send}
        onPreview={c.previewPrompt}
        webSearchAvailable={c.webSearchAvailable}
        enableWebSearch={c.enableWebSearch}
        setEnableWebSearch={c.setEnableWebSearch}
        attachments={c.attachments}
        attachmentLimits={c.attachmentLimits}
        onAddAttachments={c.addAttachmentFiles}
        onRemoveAttachment={c.removeAttachment}
      />

      {c.previewData && c.isPreviewModalOpen && (
        <ChatPromptPreviewModal preview={c.previewData} onClose={c.closePreviewModal} />
      )}
    </div>
  )
}
