import ReactMarkdown from 'react-markdown'

import { rehypePlugins, remarkPlugins } from '../../markdown/gfmSanitizedMarkdownPlugins'

export type ChatMarkdownContentProps = {
  /** レンダリングする Markdown 本文（GFM を含む） */
  readonly markdown: string
}

/**
 * チャットバブル内の Markdown を `react-markdown` で描画する薄いラッパー。
 * ダイジェストパネルと同じ GFM + サニタイズパイプラインを共有する。
 */
export function ChatMarkdownContent({ markdown }: ChatMarkdownContentProps) {
  return (
    <div className="digest-markdown chat-panel__markdown">
      <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins}>
        {markdown}
      </ReactMarkdown>
    </div>
  )
}
