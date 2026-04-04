import type { Schema } from 'hast-util-sanitize'
import type { PluggableList } from 'unified'
import rehypeHighlight from 'rehype-highlight'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'

/**
 * `rehype-highlight` が付与する `span.hljs-*` と `code.hljs` を許可しつつ、
 * GitHub 風 `defaultSchema` の XSS 抑止を維持する。
 *
 * `hast-util-sanitize` は同一属性名の定義が複数あると先頭のみ参照するため、
 * `code` の `className` は `language-*` と `hljs` を 1 タプルにまとめる。
 */
const markdownSanitizeSchema: Schema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    span: [
      ...(defaultSchema.attributes?.span ?? []),
      ['className', /^hljs-./],
    ],
    code: [['className', /^language-./, /^hljs$/]],
  },
}

/**
 * チャット・ダイジェスト共通の `react-markdown` 用 remark プラグイン一覧。
 * GFM（表・取り消し線・タスクリスト等）を有効にする。
 */
export const remarkPlugins = [remarkGfm]

/**
 * チャット・ダイジェスト共通の `react-markdown` 用 rehype プラグイン一覧。
 *
 * 順序: 先に `rehype-highlight` でフェンス付きコードを着色し、続けて拡張した
 * `rehype-sanitize` で最終出力を検査する。ユーザー入力とハイライト由来のノードが
 * 同一スキーマでサニタイズされ、`javascript:` 等は除去される。
 *
 * GFM の ```ts フェンスは `language-ts` となり、lowlight common の登録名 `typescript`
 * と不一致になるため、`typescript` 文法に `ts` エイリアスを登録する。
 */
export const rehypePlugins: PluggableList = [
  [rehypeHighlight, { aliases: { typescript: 'ts' } }],
  [rehypeSanitize, markdownSanitizeSchema],
]
