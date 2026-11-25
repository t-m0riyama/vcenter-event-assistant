import { Buffer } from 'node:buffer'
import { generateKeyPairSync, randomBytes } from 'node:crypto'

const pemLabel = 'OPENSSH PRIVATE KEY-----'
export const opensshPrivateKeyBegin = `-----BEGIN ${pemLabel}`
const opensshPrivateKeyEnd = `-----END ${pemLabel}`

function uint32(value: number) {
  const bytes = Buffer.alloc(4)
  bytes.writeUInt32BE(value)
  return bytes
}

function sshString(value: string | Buffer) {
  const bytes = Buffer.from(value)
  return Buffer.concat([uint32(bytes.length), bytes])
}

function jwkBytes(value: string | undefined) {
  if (!value) throw new Error('生成した鍵に必要な JWK の項目がありません。')
  return Buffer.from(value, 'base64url')
}

function mpint(value: string | undefined) {
  const bytes = jwkBytes(value)
  const firstNonZero = bytes.findIndex(byte => byte !== 0)
  if (firstNonZero === -1) return sshString('')
  const magnitude = bytes.subarray(firstNonZero)
  // SSH の mpint は符号付き。JWK の正整数の最上位ビットが立つ場合は 0 を付ける。
  return sshString(magnitude[0] & 0x80 ? Buffer.concat([Buffer.alloc(1), magnitude]) : magnitude)
}

function encodeKey(algorithm: string, publicFields: Buffer[], privateFields: Buffer[]) {
  const type = sshString(algorithm)
  const publicBlob = Buffer.concat([type, ...publicFields])
  const check = randomBytes(4)
  const privateBlock = Buffer.concat([check, check, type, ...privateFields, sshString('')])
  // 非暗号化 OpenSSH のブロックサイズは 8 バイト。パディングは 1, 2, … の順。
  const padding = Buffer.from(Array.from({ length: (8 - privateBlock.length % 8) % 8 }, (_, i) => i + 1))
  const envelope = Buffer.concat([
    Buffer.from('openssh-key-v1\0'),
    sshString('none'),
    sshString('none'),
    sshString(''),
    uint32(1),
    sshString(publicBlob),
    sshString(Buffer.concat([privateBlock, padding])),
  ])
  const lines = envelope.toString('base64').match(/.{1,70}/g) ?? []
  return {
    algorithm,
    privateKey: [opensshPrivateKeyBegin, ...lines, opensshPrivateKeyEnd, ''].join('\n'),
    publicKey: `${algorithm} ${publicBlob.toString('base64')}\n`,
  }
}

// テスト実行時だけ鍵を生成し、ファイルには書き出さない。
export function generateSshUploadKeys() {
  const ec = generateKeyPairSync('ec', { namedCurve: 'P-256' }).privateKey.export({ format: 'jwk' })
  const ecPublic = [
    sshString('nistp256'),
    sshString(Buffer.concat([Buffer.from([4]), jwkBytes(ec.x), jwkBytes(ec.y)])),
  ]

  const rsa = generateKeyPairSync('rsa', { modulusLength: 2048 }).privateKey.export({ format: 'jwk' })
  const exponent = mpint(rsa.e)
  const modulus = mpint(rsa.n)

  const ed = generateKeyPairSync('ed25519').privateKey.export({ format: 'jwk' })
  const edPublic = jwkBytes(ed.x)

  return [
    encodeKey('ecdsa-sha2-nistp256', ecPublic, [...ecPublic, mpint(ec.d)]),
    encodeKey('ssh-rsa', [exponent, modulus], [modulus, exponent, mpint(rsa.d), mpint(rsa.qi), mpint(rsa.p), mpint(rsa.q)]),
    encodeKey('ssh-ed25519', [sshString(edPublic)], [sshString(edPublic), sshString(Buffer.concat([jwkBytes(ed.d), edPublic]))]),
  ]
}
