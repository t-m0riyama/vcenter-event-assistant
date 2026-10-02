import type { ChatAttachmentDraft, ChatAttachmentPayload } from './chatAttachmentTypes'

/** 送信可能な添付だけを API のペイロード配列にする。 */
export function buildChatAttachmentPayloads(
  drafts: readonly ChatAttachmentDraft[],
): ChatAttachmentPayload[] {
  const out: ChatAttachmentPayload[] = []
  for (const d of drafts) {
    if (d.status === 'ready' && d.payload) {
      out.push(d.payload)
    }
  }
  return out
}

/** 1 件でも読み取り中・エラーの添付があるか（送信を止める判定に使う）。 */
export function hasBlockingChatAttachment(drafts: readonly ChatAttachmentDraft[]): boolean {
  return drafts.some((d) => d.status !== 'ready')
}
