import { describe, expect, it } from 'vitest'

import { appendChatSampleTextToDraft } from './appendChatSampleTextToDraft'

describe('appendChatSampleTextToDraft', () => {
  it('空下書きへ本文を入れる', () => {
    expect(appendChatSampleTextToDraft('', 'First')).toBe('First')
  })

  it('既存下書きがあるとき末尾に \\n\\n で追記する', () => {
    expect(appendChatSampleTextToDraft('Hello', 'First')).toBe('Hello\n\nFirst')
  })

  it('追記本文が trim 後に空なら下書きを変えない', () => {
    expect(appendChatSampleTextToDraft('Hi', '   ')).toBe('Hi')
  })

  it('本文は trim してから連結する', () => {
    expect(appendChatSampleTextToDraft('', '  body  ')).toBe('body')
  })

  it('連続追記はクリック順で連結される', () => {
    const afterFirst = appendChatSampleTextToDraft('', 'First')
    expect(appendChatSampleTextToDraft(afterFirst, 'Second')).toBe('First\n\nSecond')
  })
})
