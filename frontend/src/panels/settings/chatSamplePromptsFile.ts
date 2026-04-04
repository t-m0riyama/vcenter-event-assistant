import { z } from 'zod'

import type { ChatSamplePromptRow } from '../chat/chatSamplePromptTypes'

const rowSchema = z.object({
  id: z.string().min(1),
  label: z.string(),
  text: z.string(),
})

export const chatSamplePromptsFileSchema = z.object({
  format: z.literal('vea-chat-sample-prompts'),
  version: z.number().int().positive(),
  exported_at: z.string(),
  samples: z.array(rowSchema),
})

export type ChatSamplePromptsFile = z.infer<typeof chatSamplePromptsFileSchema>

/**
 * エクスポート用 JSON。保存済みの全サンプル行を含む。
 */
export function buildChatSamplePromptsExportPayload(
  samples: readonly ChatSamplePromptRow[],
): ChatSamplePromptsFile {
  return {
    format: 'vea-chat-sample-prompts',
    version: 1,
    exported_at: new Date().toISOString(),
    samples: samples.map((r) => ({ id: r.id, label: r.label, text: r.text })),
  }
}

export type ChatSamplePromptsImportMergeOptions = {
  readonly overwriteExisting: boolean
  readonly deleteNotInImport: boolean
}

/**
 * ファイルの samples と現在の一覧をマージする。出現順は「ファイル内の id 順（初出）→ 残りは既存の並び」。
 */
export function mergeChatSamplePromptsImport(
  current: readonly ChatSamplePromptRow[],
  fileRows: readonly ChatSamplePromptRow[],
  opts: ChatSamplePromptsImportMergeOptions,
): ChatSamplePromptRow[] {
  const fileIds = new Set(fileRows.map((r) => r.id))

  let working: ChatSamplePromptRow[]
  if (opts.deleteNotInImport) {
    working = current.filter((r) => fileIds.has(r.id))
  } else {
    working = [...current]
  }

  const byId = new Map(working.map((r) => [r.id, r]))

  for (const row of fileRows) {
    const copy: ChatSamplePromptRow = { id: row.id, label: row.label, text: row.text }
    if (byId.has(row.id)) {
      if (opts.overwriteExisting) {
        byId.set(row.id, copy)
      }
    } else {
      byId.set(row.id, copy)
    }
  }

  const fileOrderUniqueIds: string[] = []
  const seen = new Set<string>()
  for (const r of fileRows) {
    if (!seen.has(r.id)) {
      seen.add(r.id)
      fileOrderUniqueIds.push(r.id)
    }
  }

  const result: ChatSamplePromptRow[] = []
  const inResult = new Set<string>()
  for (const id of fileOrderUniqueIds) {
    const r = byId.get(id)
    if (r) {
      result.push(r)
      inResult.add(id)
    }
  }
  for (const r of working) {
    if (!inResult.has(r.id)) {
      const row = byId.get(r.id)
      if (row) {
        result.push(row)
        inResult.add(r.id)
      }
    }
  }
  return result
}
