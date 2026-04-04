import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ChatMarkdownContent } from '../panels/chat/ChatMarkdownContent'

describe('ChatMarkdownContent', () => {
  it('javascript: スキームのリンクは出力に含めない', () => {
    const { container } = render(
      <ChatMarkdownContent markdown={'悪意のあるリンク [x](javascript:alert(1))'} />,
    )
    const javascriptLinks = container.querySelectorAll('a[href^="javascript:"]')
    expect(javascriptLinks.length).toBe(0)
  })

  it('通常の Markdown 段落が描画される', () => {
    render(<ChatMarkdownContent markdown="これは通常の段落です。" />)
    expect(screen.getByText('これは通常の段落です。')).toBeInTheDocument()
  })

  it('フェンス付きコードにシンタックスハイライト用のクラスが付く', () => {
    const { container } = render(
      <ChatMarkdownContent markdown={'```ts\nconst x = 1\n```'} />,
    )
    const code = container.querySelector('pre code')
    expect(code).toBeTruthy()
    expect(code?.className).toMatch(/\bhljs\b/)
    expect(code?.querySelector('span.hljs-keyword')).toBeTruthy()
  })
})
