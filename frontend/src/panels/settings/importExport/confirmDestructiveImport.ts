/** インポート時「ファイルに含まれない項目を削除」確認ダイアログの文言。 */
export type DestructiveImportConfirmMessages = {
  readonly emptyImportConfirm: string
  readonly deleteNotInFileConfirm: string
}

/** アラートルール破壊的 import 確認ダイアログの文言。 */
export const ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES: DestructiveImportConfirmMessages = {
  emptyImportConfirm:
    'このファイルにはルールが含まれていません。既存のアラートルールをすべて削除します。よろしいですか？',
  deleteNotInFileConfirm: 'ファイルに含まれないアラートルールは削除されます。よろしいですか？',
}

/** スコアルール破壊的 import 確認ダイアログの文言。 */
export const SCORE_RULES_DESTRUCTIVE_IMPORT_MESSAGES: DestructiveImportConfirmMessages = {
  emptyImportConfirm:
    'このファイルにはルールが含まれていません。既存のルールをすべて削除します。よろしいですか？',
  deleteNotInFileConfirm:
    'ファイルに含まれないイベント種別のルールは削除されます。よろしいですか？',
}

/** イベント種別ガイド破壊的 import 確認ダイアログの文言。 */
export const EVENT_TYPE_GUIDES_DESTRUCTIVE_IMPORT_MESSAGES: DestructiveImportConfirmMessages = {
  emptyImportConfirm:
    'このファイルにはガイドが含まれていません。既存のガイドをすべて削除します。よろしいですか？',
  deleteNotInFileConfirm:
    'ファイルに含まれないイベント種別のガイドは削除されます。よろしいですか？',
}

/**
 * 「ファイルに含まれない項目を削除」がオンのとき、confirm で続行可否を返す。
 * オフのときは確認なしで true。
 */
export function confirmDestructiveImport(
  deleteNotInImport: boolean,
  itemCount: number,
  messages: DestructiveImportConfirmMessages,
  confirmFn: (message: string) => boolean = (message) => globalThis.confirm(message),
): boolean {
  if (!deleteNotInImport) return true
  if (itemCount === 0) {
    return confirmFn(messages.emptyImportConfirm)
  }
  return confirmFn(messages.deleteNotInFileConfirm)
}
