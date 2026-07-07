import './ChatPanel.css'

import { useChatSamplePrompts } from '../../preferences/useChatSamplePrompts'
import { ChatContextBar } from './ChatContextBar'
import { ChatInputBar } from './ChatInputBar'
import { ChatMessagesList } from './ChatMessagesList'
import { ChatPromptPreviewModal } from './ChatPromptPreviewModal'
import { useChatPanelController } from '../../hooks/useChatPanelController'

/**
 * 期間集約コンテキスト付きの LLM チャットパネル。会話リストは最下部付近にいるときだけ追従し、
 * アシスタント応答後はそのメッセージ先頭が見える位置へ、ユーザーのみ末尾のときはリスト最下端へ寄せる。
 * 送信中はリスト末尾にプレースホルダ行を出し、`aria-busy` で状態を示す。
 * サンプル質問はチップをクリックすると textarea 末尾へ即時追記する（送信はしない。`ChatSamplePromptsProvider` 必須）。
 */
export function ChatPanel({ onError }: { onError: (e: string | null) => void }) {
  const { visibleChatSamplePrompts } = useChatSamplePrompts()
  const c = useChatPanelController(onError)

  return (
    <div className="panel chat-panel">
      <p className="hint">
        指定期間のイベント・メトリクス集約を根拠に、質問・追質問ができます（会話はブラウザに保持し、サーバーは保存しません）。
      </p>

      <ChatContextBar
        rangeParts={c.rangeParts}
        setRangeParts={c.setRangeParts}
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
        includeResearch={c.includeResearch}
        setIncludeResearch={c.setIncludeResearch}
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

      <ChatInputBar
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
      />

      {c.previewData && c.isPreviewModalOpen && (
        <ChatPromptPreviewModal preview={c.previewData} onClose={c.closePreviewModal} />
      )}
    </div>
  )
}
