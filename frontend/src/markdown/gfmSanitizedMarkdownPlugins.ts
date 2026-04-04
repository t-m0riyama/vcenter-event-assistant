import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

/**
 * チャット・ダイジェスト共通の `react-markdown` 用 remark プラグイン一覧。
 * GFM（表・取り消し線・タスクリスト等）を有効にする。
 */
export const remarkPlugins = [remarkGfm]

/**
 * チャット・ダイジェスト共通の `react-markdown` 用 rehype プラグイン一覧。
 * `rehype-sanitize` の既定スキーマ（GitHub 風）で XSS を抑止する。
 */
export const rehypePlugins = [rehypeSanitize]
