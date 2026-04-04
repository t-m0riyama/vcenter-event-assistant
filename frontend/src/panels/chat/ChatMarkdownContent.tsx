import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type Props = {
  /** 会話バブル内に描画する Markdown（GFM 拡張を含む） */
  readonly markdown: string
}

/**
 * チャットメッセージ本文を GFM 対応の Markdown として表示する。
 * スタイルは `.digest-markdown` と共有する。
 */
export function ChatMarkdownContent({ markdown }: Props) {
  return (
    <div className="digest-markdown chat-panel__markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  )
}
