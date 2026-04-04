import { describe, expect, it } from 'vitest'

import { appendSelectedChatSampleTextsToDraft } from './appendSelectedChatSampleTextsToDraft'

describe('appendSelectedChatSampleTextsToDraft', () => {
  const ordered = [
    { id: 'a', text: 'First' },
    { id: 'b', text: 'Second' },
  ]

  it('選択 id を一覧の定義順で連結し、\\n\\n で区切って空下書きへ入れる', () => {
    expect(appendSelectedChatSampleTextsToDraft('', ordered, new Set(['b', 'a']))).toBe(
      'First\n\nSecond',
    )
  })

  it('既存下書きがあるとき末尾に \\n\\n で追記する', () => {
    expect(appendSelectedChatSampleTextsToDraft('Hello', ordered, new Set(['a']))).toBe(
      'Hello\n\nFirst',
    )
  })

  it('選択が空のとき下書きを変えない', () => {
    expect(appendSelectedChatSampleTextsToDraft('Hi', ordered, new Set())).toBe('Hi')
  })

  it('各 text は trim してから連結する', () => {
    const rows = [{ id: 'x', text: '  body  ' }]
    expect(appendSelectedChatSampleTextsToDraft('', rows, new Set(['x']))).toBe('body')
  })

  it('trim 後に空になる text は連結から除外する', () => {
    const rows = [
      { id: 'a', text: 'OK' },
      { id: 'b', text: '   ' },
    ]
    expect(appendSelectedChatSampleTextsToDraft('', rows, new Set(['a', 'b']))).toBe('OK')
  })
})
