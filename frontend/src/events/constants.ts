/** イベント一覧のページサイズ選択肢。 */
export const EVENT_PAGE_SIZES = [20, 50, 100, 200] as const

/** ``GET /api/events`` の ``limit`` 上限（チャンク export 用）。 */
export const EVENT_EXPORT_CHUNK = 200

/** テキストフィルタ要約の省略表示文字数。 */
export const EVENT_TEXT_FILTER_SUMMARY_CLIP = 18
/** テキストフィルタ要約の最大文字数。 */
export const EVENT_TEXT_FILTER_SUMMARY_MAX = 96
