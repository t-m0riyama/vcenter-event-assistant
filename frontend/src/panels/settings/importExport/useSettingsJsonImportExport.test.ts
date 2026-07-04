/**
 * @vitest-environment happy-dom
 */
import { renderHook, act } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { z } from 'zod'

import { useSettingsJsonImportExport } from './useSettingsJsonImportExport'
import { SCORE_RULES_DESTRUCTIVE_IMPORT_MESSAGES } from './confirmDestructiveImport'

const fileSchema = z.object({
  format: z.literal('test'),
  version: z.number(),
  rules: z.array(z.object({ event_type: z.string(), score_delta: z.number() })),
})

describe('useSettingsJsonImportExport', () => {
  const onError = vi.fn()
  const onImportComplete = vi.fn().mockResolvedValue(undefined)
  const downloadJsonFile = vi.fn()

  beforeEach(() => {
    onError.mockReset()
    onImportComplete.mockReset().mockResolvedValue(undefined)
    downloadJsonFile.mockReset()
    vi.stubGlobal('confirm', vi.fn(() => true))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  function makeConfig() {
    return {
      exportFilenamePrefix: 'vea-test-rules',
      buildExportPayload: () => ({ format: 'test', version: 1, rules: [] }),
      fileSchema,
      getImportItemCount: (file: z.infer<typeof fileSchema>) => file.rules.length,
      buildImportRequestBody: (
        file: z.infer<typeof fileSchema>,
        options: { overwriteExisting: boolean; deleteNotInImport: boolean },
      ) => ({
        overwrite_existing: options.overwriteExisting,
        delete_rules_not_in_import: options.deleteNotInImport,
        rules: file.rules,
      }),
      importPath: '/api/event-score-rules/import',
      importResponseSchema: z.object({ rules_count: z.number() }),
      destructiveMessages: SCORE_RULES_DESTRUCTIVE_IMPORT_MESSAGES,
      formatFileParseError: () => 'parse error',
      formatImportApiError: () => 'api error',
      onError,
      onImportComplete,
      downloadJsonFile,
    }
  }

  it('exportToFile が payload を JSON ダウンロードする', () => {
    const { result } = renderHook(() => useSettingsJsonImportExport(makeConfig()))
    act(() => {
      result.current.exportToFile()
    })
    expect(onError).toHaveBeenCalledWith(null)
    expect(downloadJsonFile).toHaveBeenCalledWith(
      expect.stringMatching(/^vea-test-rules-\d{4}-\d{2}-\d{2}\.json$/),
      { format: 'test', version: 1, rules: [] },
    )
  })

  it('有効な import ファイルで API POST 後に onImportComplete を呼ぶ', async () => {
    const apiPost = vi.fn().mockResolvedValue({ rules_count: 1 })
    const { result } = renderHook(() =>
      useSettingsJsonImportExport({ ...makeConfig(), apiPost }),
    )

    const file = new File(
      [JSON.stringify({ format: 'test', version: 1, rules: [{ event_type: 'a', score_delta: 1 }] })],
      'rules.json',
      { type: 'application/json' },
    )
    const input = document.createElement('input')
    input.type = 'file'
    const dt = new DataTransfer()
    dt.items.add(file)
    input.files = dt.files

    await act(async () => {
      await result.current.onImportFileChange({ target: input } as React.ChangeEvent<HTMLInputElement>)
    })

    expect(apiPost).toHaveBeenCalledWith('/api/event-score-rules/import', {
      overwrite_existing: true,
      delete_rules_not_in_import: false,
      rules: [{ event_type: 'a', score_delta: 1 }],
    })
    expect(onImportComplete).toHaveBeenCalled()
  })
})
