import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export type ChatMarkdownContentProps = {
  /** レンダリングする Markdown 本文（GFM を含む） */
  readonly markdown: string
}

/**
 * チャットバブル内の Markdown を `react-markdown` と `remark-gfm` で描画する薄いラッパー。
 * ダイジェストパネルと同じ GFM パイプライン（`remarkPlugins={[remarkGfm]}`）を共有する。
 */
export function ChatMarkdownContent({ markdown }: ChatMarkdownContentProps) {
  return (
    <div className="digest-markdown chat-panel__markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  )
}
