/** チャットのタブに渡す「この期間・この vCenter で質問したい」という条件。対象（entity）などの絞り込みは渡せない。 */
export type ChatHandoff = {
  /** 期間（UTC の ISO 8601）。 */
  from: string
  to: string
  /** null は vCenter の指定なし（すべて）。 */
  vcenterId: string | null
}

/** チャットのタブで一度だけ適用する条件。`nonce` が変わるたびに適用し直す。 */
export type ChatHandoffInput = { focus: ChatHandoff; nonce: number }
