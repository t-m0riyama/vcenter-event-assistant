/** チャットのタブに渡す「この期間・この vCenter で質問したい」という条件。対象（entity）などの絞り込みは渡せない。 */
export type ChatHandoff = {
  /** 期間（UTC の ISO 8601）。秒・ミリ秒まで、そのままチャットの送信に使う。 */
  from: string
  to: string
  /** null は vCenter の指定なし（すべて）。 */
  vcenterId: string | null
  /** タイムラインで絞っていて、チャットには引き継がれないもの（「対象」「起点」など）。注記に出す。 */
  narrowedBy: string[]
  /** 保存済みのスナップショットの表示中に渡したか。チャットは現在のデータを集計するので、注記で伝える。 */
  fromSavedSnapshot: boolean
}

/** チャットのタブで一度だけ適用する条件。`nonce` が変わるたびに適用する（適用したら呼び出し側が消す）。 */
export type ChatHandoffInput = { focus: ChatHandoff; nonce: number }
