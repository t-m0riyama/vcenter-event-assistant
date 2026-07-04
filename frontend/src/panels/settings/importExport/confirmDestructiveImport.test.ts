import { describe, expect, it, vi } from 'vitest'

import {
  ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES,
  confirmDestructiveImport,
} from './confirmDestructiveImport'

describe('confirmDestructiveImport', () => {
  it('deleteNotInImport がオフのときは確認なしで true', () => {
    const confirmFn = vi.fn()
    expect(
      confirmDestructiveImport(false, 0, ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES, confirmFn),
    ).toBe(true)
    expect(confirmFn).not.toHaveBeenCalled()
  })

  it('deleteNotInImport オンかつ件数 0 のとき empty メッセージで確認する', () => {
    const confirmFn = vi.fn().mockReturnValue(false)
    expect(
      confirmDestructiveImport(true, 0, ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES, confirmFn),
    ).toBe(false)
    expect(confirmFn).toHaveBeenCalledWith(
      ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES.emptyImportConfirm,
    )
  })

  it('deleteNotInImport オンかつ件数 > 0 のとき deleteNotInFile メッセージで確認する', () => {
    const confirmFn = vi.fn().mockReturnValue(true)
    expect(
      confirmDestructiveImport(true, 3, ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES, confirmFn),
    ).toBe(true)
    expect(confirmFn).toHaveBeenCalledWith(
      ALERT_RULES_DESTRUCTIVE_IMPORT_MESSAGES.deleteNotInFileConfirm,
    )
  })
})
