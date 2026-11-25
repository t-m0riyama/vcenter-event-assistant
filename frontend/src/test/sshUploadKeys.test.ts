import { Buffer } from 'node:buffer'
import { expect, it } from 'vitest'
import { generateSshUploadKeys, opensshPrivateKeyBegin } from './sshUploadKeys'

it.each(generateSshUploadKeys())('$algorithm の秘密鍵に対応する公開鍵が埋め込まれている', ({ algorithm, privateKey, publicKey }) => {
  const [header, ...rest] = privateKey.trimEnd().split('\n')
  const lines = rest.slice(0, -1)
  expect(header).toBe(opensshPrivateKeyBegin)
  expect(lines.slice(0, -1).every(line => line.length === 70)).toBe(true)
  const bytes = Buffer.from(lines.join(''), 'base64')
  const magic = 'openssh-key-v1\0'
  expect(bytes.toString('ascii', 0, magic.length)).toBe(magic)
  let offset = magic.length
  const readString = () => {
    const length = bytes.readUInt32BE(offset)
    const start = offset + 4
    offset = start + length
    return bytes.subarray(start, offset)
  }
  expect(readString().toString()).toBe('none')
  expect(readString().toString()).toBe('none')
  expect(readString()).toHaveLength(0)
  expect(bytes.readUInt32BE(offset)).toBe(1)
  offset += 4
  const [type, encoded] = publicKey.trimEnd().split(' ')
  expect(type).toBe(algorithm)
  expect(readString()).toEqual(Buffer.from(encoded, 'base64'))
})
