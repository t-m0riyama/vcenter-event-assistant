import { useCallback, useRef, useState } from 'react'
import type { ChangeEvent, RefObject } from 'react'
import type { ZodType } from 'zod'

import { apiPost } from '../../../api'
import { downloadJsonFile } from '../../../utils/downloadJsonFile'
import { toErrorMessage } from '../../../utils/errors'
import { buildVeaExportFilename } from './buildExportFilename'
import { UNPARSEABLE_IMPORT_RESPONSE_MESSAGE } from './constants'
import {
  confirmDestructiveImport,
  type DestructiveImportConfirmMessages,
} from './confirmDestructiveImport'
import { parseJsonImportFile, takeFirstImportFile } from './parseJsonImportFile'

export type SettingsJsonImportExportOptions = {
  overwriteExisting: boolean
  deleteNotInImport: boolean
}

export type UseSettingsJsonImportExportConfig<TFile> = {
  exportFilenamePrefix: string
  buildExportPayload: () => unknown
  fileSchema: ZodType<TFile>
  getImportItemCount: (file: TFile) => number
  buildImportRequestBody: (file: TFile, options: SettingsJsonImportExportOptions) => unknown
  importPath: string
  importResponseSchema: ZodType<unknown>
  destructiveMessages: DestructiveImportConfirmMessages
  formatFileParseError: (err: unknown) => string
  formatImportApiError: (err: unknown) => string
  onError: (msg: string | null) => void
  onImportComplete: () => Promise<void>
  /** テストで差し替え可能にするため optional。未指定時は downloadJsonFile を使用。 */
  downloadJsonFile?: (filename: string, value: unknown) => void
  /** テストで差し替え可能にするため optional。未指定時は apiPost を使用。 */
  apiPost?: typeof apiPost
}

export type UseSettingsJsonImportExportResult = {
  overwriteExisting: boolean
  setOverwriteExisting: (value: boolean) => void
  deleteNotInImport: boolean
  setDeleteNotInImport: (value: boolean) => void
  fileInputRef: RefObject<HTMLInputElement | null>
  exportToFile: () => void
  onImportFileChange: (event: ChangeEvent<HTMLInputElement>) => Promise<void>
  openImportFilePicker: () => void
}

/**
 * 設定パネル共通の JSON エクスポート・インポート状態とハンドラ。
 */
export function useSettingsJsonImportExport<TFile>(
  config: UseSettingsJsonImportExportConfig<TFile>,
): UseSettingsJsonImportExportResult {
  const {
    exportFilenamePrefix,
    buildExportPayload,
    fileSchema,
    getImportItemCount,
    buildImportRequestBody,
    importPath,
    importResponseSchema,
    destructiveMessages,
    formatFileParseError,
    formatImportApiError,
    onError,
    onImportComplete,
    downloadJsonFile: downloadJsonFileFn = downloadJsonFile,
    apiPost: apiPostFn = apiPost,
  } = config

  const [overwriteExisting, setOverwriteExisting] = useState(true)
  const [deleteNotInImport, setDeleteNotInImport] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const exportToFile = useCallback(() => {
    onError(null)
    try {
      const payload = buildExportPayload()
      const name = buildVeaExportFilename(exportFilenamePrefix)
      downloadJsonFileFn(name, payload)
    } catch (err) {
      onError(toErrorMessage(err))
    }
  }, [buildExportPayload, downloadJsonFileFn, exportFilenamePrefix, formatImportApiError, onError])

  const onImportFileChange = useCallback(
    async (event: ChangeEvent<HTMLInputElement>) => {
      const file = takeFirstImportFile(event.target)
      if (!file) return

      const parsed = await parseJsonImportFile(file, fileSchema)
      if (!parsed.ok) {
        onError(formatFileParseError(parsed.error))
        return
      }

      const importOptions = { overwriteExisting, deleteNotInImport }
      if (
        !confirmDestructiveImport(
          deleteNotInImport,
          getImportItemCount(parsed.data),
          destructiveMessages,
        )
      ) {
        return
      }

      onError(null)
      try {
        const raw = await apiPostFn(importPath, buildImportRequestBody(parsed.data, importOptions))
        try {
          importResponseSchema.parse(raw)
        } catch {
          onError(UNPARSEABLE_IMPORT_RESPONSE_MESSAGE)
          return
        }
        await onImportComplete()
      } catch (err) {
        onError(formatImportApiError(err))
      }
    },
    [
      apiPostFn,
      buildImportRequestBody,
      deleteNotInImport,
      destructiveMessages,
      fileSchema,
      formatFileParseError,
      formatImportApiError,
      getImportItemCount,
      importPath,
      importResponseSchema,
      onError,
      onImportComplete,
      overwriteExisting,
    ],
  )

  const openImportFilePicker = useCallback(() => {
    fileInputRef.current?.click()
  }, [])

  return {
    overwriteExisting,
    setOverwriteExisting,
    deleteNotInImport,
    setDeleteNotInImport,
    fileInputRef,
    exportToFile,
    onImportFileChange,
    openImportFilePicker,
  }
}
