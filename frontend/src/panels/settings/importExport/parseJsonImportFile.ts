import type { ZodType } from 'zod'

export type ParseJsonImportFileResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: unknown }

/**
 * ファイル選択 input から先頭ファイルを取り出し、value をクリアする。
 */
export function takeFirstImportFile(input: HTMLInputElement): File | null {
  const file = input.files?.[0] ?? null
  input.value = ''
  return file
}

/**
 * JSON インポートファイルを読み込み、Zod schema で検証する。
 */
export async function parseJsonImportFile<T>(
  file: File,
  schema: ZodType<T>,
): Promise<ParseJsonImportFileResult<T>> {
  try {
    const text = await file.text()
    const json: unknown = JSON.parse(text)
    return { ok: true, data: schema.parse(json) }
  } catch (error) {
    return { ok: false, error }
  }
}
