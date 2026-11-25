export const privateKeyHeader = /-----BEGIN [^\r\n]*PRIVATE KEY(?: BLOCK)?-----/

function embeddedPublicKey(body: string) {
  try {
    const binary = atob(body)
    const magic = 'openssh-key-v1\0'
    if (!binary.startsWith(magic)) return ''
    const bytes = new DataView(Uint8Array.from(binary, char => char.charCodeAt(0)).buffer)
    let offset = magic.length
    const readLength = () => {
      const length = bytes.getUint32(offset)
      offset += 4
      return length
    }
    // 暗号、鍵導出方式、その設定、鍵の個数に続いて公開鍵が入る。
    for (let i = 0; i < 3; i += 1) {
      const length = readLength()
      offset += length
    }
    if (readLength() !== 1) return ''
    const length = readLength()
    if (offset + length > binary.length) return ''
    return btoa(binary.slice(offset, offset + length))
  } catch {
    return ''
  }
}

/**
 * `message` に `privateKey` が含まれているかを調べる。
 * `unknownFormat` が `strict` のときは、埋め込まれた公開鍵を取り出せない鍵（PEM 形式など）で、
 * 本文の断片が 1 つでも含まれれば伏せる。エラーの文言向けで、伏せすぎても困らない。
 * 成功応答の公開鍵を調べるときは `lenient` にする。PEM 形式の本文と公開鍵は同じ値を含むため、
 * 断片の一致では正しい公開鍵まで誤検知することがある。
 */
export function reflectsPrivateKey(
  rawMessage: string,
  privateKey: string,
  unknownFormat: 'strict' | 'lenient' = 'strict',
) {
  if (privateKeyHeader.test(rawMessage)) return true
  // repr や二重にエスケープした JSON の「\n」などの文字を、断片の切れ目として扱う。
  const message = rawMessage.replace(/\\[nrt]/g, ' ')
  const trimmed = privateKey.trim()
  if (trimmed && (message.includes(trimmed) || message.includes(JSON.stringify(trimmed).slice(1, -1)))) return true

  const lines = trimmed.split(/\r?\n/).filter(line => /^[A-Za-z0-9+/]+={0,2}$/.test(line))
  const body = lines.join('')
  // 鍵全体の本文は、改行が省かれたり変わったりしていても伏せる。
  if (body.length >= 24 && message.replace(/\s/g, '').includes(body)) return true

  // OpenSSH の本文には公開鍵も含まれる。本文の一部は公開鍵にない断片だけを伏せる。
  const publicKey = embeddedPublicKey(body)
  const fragments = message.match(/[A-Za-z0-9+/]{24,}={0,2}/g) ?? []
  if (publicKey === '') return unknownFormat === 'strict' && fragments.some(fragment => body.includes(fragment))
  return fragments.some(fragment => body.includes(fragment) && !publicKey.includes(fragment))
}
