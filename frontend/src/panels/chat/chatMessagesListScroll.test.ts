import { describe, expect, it } from 'vitest'

import {
  CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
  computeScrollTopToShowChildAtListTop,
} from './chatMessagesListScroll'

describe('computeScrollTopToShowChildAtListTop', () => {
  it('子の offsetTop から margin を引き、0〜maxScroll に収める', () => {
    expect(
      computeScrollTopToShowChildAtListTop({
        childOffsetTop: 900,
        scrollHeight: 1200,
        clientHeight: 200,
        marginPx: CHAT_ASSISTANT_MESSAGE_LIST_TOP_MARGIN_PX,
      }),
    ).toBe(892)
  })

  it('childOffsetTop が margin 以下なら 0', () => {
    expect(
      computeScrollTopToShowChildAtListTop({
        childOffsetTop: 4,
        scrollHeight: 500,
        clientHeight: 200,
        marginPx: 8,
      }),
    ).toBe(0)
  })

  it('上端寄せの raw が maxScroll を超えると maxScroll にクランプ', () => {
    expect(
      computeScrollTopToShowChildAtListTop({
        childOffsetTop: 5000,
        scrollHeight: 1200,
        clientHeight: 200,
        marginPx: 8,
      }),
    ).toBe(1000)
  })

  it('コンテンツが窓より低いとき maxScroll は 0 でクランプされる', () => {
    expect(
      computeScrollTopToShowChildAtListTop({
        childOffsetTop: 100,
        scrollHeight: 150,
        clientHeight: 200,
        marginPx: 8,
      }),
    ).toBe(0)
  })
})
