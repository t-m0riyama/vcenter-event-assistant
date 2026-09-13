import { describe, expect, it } from 'vitest'

import { buildChatAttachmentPayloads, hasBlockingChatAttachment } from './buildChatAttachmentPayloads'
import { chatAttachmentRejectionReason, formatAttachmentSize } from './chatAttachmentRejection'
import { classifyChatAttachmentFile, imageMediaTypeFor } from './classifyChatAttachmentFile'
import { dataUrlToBase64, scaleToFitMaxEdge } from './downscaleImageAttachment'
import { truncateAttachmentText } from './readTextAttachment'
import {
  DEFAULT_CHAT_ATTACHMENT_LIMITS,
  type ChatAttachmentDraft,
  type ChatAttachmentLimits,
} from './chatAttachmentTypes'

const limits: ChatAttachmentLimits = { ...DEFAULT_CHAT_ATTACHMENT_LIMITS, imagesAvailable: true }

describe('classifyChatAttachmentFile', () => {
  it('MIME からテキストと画像を判定する', () => {
    expect(classifyChatAttachmentFile({ name: 'a.txt', type: 'text/plain' })).toBe('text')
    expect(classifyChatAttachmentFile({ name: 'a.json', type: 'application/json' })).toBe('text')
    expect(classifyChatAttachmentFile({ name: 'a.png', type: 'image/png' })).toBe('image')
    expect(classifyChatAttachmentFile({ name: 'a.jpg', type: 'image/jpeg' })).toBe('image')
  })

  it('MIME が空でも拡張子で判定する（.log は MIME が付かない環境がある）', () => {
    expect(classifyChatAttachmentFile({ name: 'vmkernel.log', type: '' })).toBe('text')
    expect(classifyChatAttachmentFile({ name: 'shot.PNG', type: '' })).toBe('image')
  })

  it('対応外の形式を弾く', () => {
    expect(classifyChatAttachmentFile({ name: 'a.pdf', type: 'application/pdf' })).toBe('unsupported')
    expect(classifyChatAttachmentFile({ name: 'a.docx', type: '' })).toBe('unsupported')
    // サーバの allowlist にない画像形式
    expect(classifyChatAttachmentFile({ name: 'a.gif', type: 'image/gif' })).toBe('unsupported')
  })

  it('画像の送信 MIME を決める', () => {
    expect(imageMediaTypeFor({ name: 'a.jpg', type: '' })).toBe('image/jpeg')
    expect(imageMediaTypeFor({ name: 'a.png', type: '' })).toBe('image/png')
  })
})

describe('chatAttachmentRejectionReason', () => {
  const file = { name: 'a.log', size: 1024 }

  it('受け付けられるときは null', () => {
    expect(chatAttachmentRejectionReason(file, 'text', limits, 0)).toBeNull()
  })

  it('件数上限を超えると理由を返す', () => {
    expect(chatAttachmentRejectionReason(file, 'text', limits, limits.maxFiles)).toContain(
      `${limits.maxFiles} 件`,
    )
  })

  it('サイズ上限を超えると理由を返す', () => {
    const big = { name: 'a.log', size: limits.maxFileBytes + 1 }
    expect(chatAttachmentRejectionReason(big, 'text', limits, 0)).toContain('大きすぎます')
  })

  it('空ファイルを弾く', () => {
    expect(chatAttachmentRejectionReason({ name: 'a.log', size: 0 }, 'text', limits, 0)).toContain(
      '空',
    )
  })

  it('対応外の形式を弾く', () => {
    expect(chatAttachmentRejectionReason(file, 'unsupported', limits, 0)).toContain('対応していない')
  })

  it('プロバイダが画像非対応なら画像を弾く', () => {
    const noImages = { ...limits, imagesAvailable: false }
    expect(chatAttachmentRejectionReason(file, 'image', noImages, 0)).toContain('画像')
  })

  it('添付が無効化されていれば全て弾く', () => {
    const disabled = { ...limits, maxFiles: 0 }
    expect(chatAttachmentRejectionReason(file, 'text', disabled, 0)).toContain('無効')
  })
})

describe('truncateAttachmentText', () => {
  it('上限以下はそのまま', () => {
    expect(truncateAttachmentText('abc', 10)).toEqual({ text: 'abc', truncated: false })
  })

  it('上限を超えたら切り詰めて印を立てる', () => {
    expect(truncateAttachmentText('abcdef', 3)).toEqual({ text: 'abc', truncated: true })
  })
})

describe('scaleToFitMaxEdge', () => {
  it('長辺が上限以下なら縮小しない', () => {
    expect(scaleToFitMaxEdge(800, 600, 1568)).toEqual({ width: 800, height: 600 })
  })

  it('アスペクト比を保って長辺を上限に合わせる', () => {
    expect(scaleToFitMaxEdge(3200, 1600, 1568)).toEqual({ width: 1568, height: 784 })
    expect(scaleToFitMaxEdge(1600, 3200, 1568)).toEqual({ width: 784, height: 1568 })
  })

  it('0 サイズでも落ちない', () => {
    expect(scaleToFitMaxEdge(0, 0, 1568)).toEqual({ width: 0, height: 0 })
  })
})

describe('dataUrlToBase64', () => {
  it('データ URL の接頭辞を落とす', () => {
    expect(dataUrlToBase64('data:image/jpeg;base64,AAAA')).toBe('AAAA')
  })

  it('接頭辞が無ければそのまま', () => {
    expect(dataUrlToBase64('AAAA')).toBe('AAAA')
  })
})

describe('buildChatAttachmentPayloads', () => {
  const ready: ChatAttachmentDraft = {
    id: '1',
    filename: 'a.log',
    sizeBytes: 10,
    kind: 'text',
    status: 'ready',
    payload: { kind: 'text', filename: 'a.log', media_type: 'text/plain', text: 'x' },
  }
  const reading: ChatAttachmentDraft = {
    id: '2',
    filename: 'b.png',
    sizeBytes: 10,
    kind: 'image',
    status: 'reading',
  }
  const failed: ChatAttachmentDraft = {
    id: '3',
    filename: 'c.pdf',
    sizeBytes: 10,
    kind: 'unsupported',
    status: 'error',
    error: 'だめ',
  }

  it('ready のものだけ送信対象にする', () => {
    expect(buildChatAttachmentPayloads([ready, reading, failed])).toEqual([ready.payload])
  })

  it('読み取り中やエラーがあれば送信を止める', () => {
    expect(hasBlockingChatAttachment([ready])).toBe(false)
    expect(hasBlockingChatAttachment([ready, reading])).toBe(true)
    expect(hasBlockingChatAttachment([ready, failed])).toBe(true)
  })
})

describe('formatAttachmentSize', () => {
  it('読めるサイズ表記にする', () => {
    expect(formatAttachmentSize(512)).toBe('512B')
    expect(formatAttachmentSize(2048)).toBe('2KB')
    expect(formatAttachmentSize(10 * 1024 * 1024)).toBe('10.0MB')
  })
})
