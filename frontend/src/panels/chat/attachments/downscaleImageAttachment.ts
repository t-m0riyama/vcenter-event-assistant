import type { ChatAttachmentPayload } from './chatAttachmentTypes'
import { imageMediaTypeFor } from './classifyChatAttachmentFile'

/**
 * 縮小後の長辺（px）。vision モデルが内部で行うリサイズと同程度に合わせてあり、
 * これ以上大きく送っても精度は上がらず、トークンと転送量だけが増える。
 */
export const IMAGE_MAX_EDGE_PX = 1568

/** 再エンコード時の JPEG 品質。 */
const JPEG_QUALITY = 0.85

/** 長辺が上限を超えるときだけ縮小する倍率を返す。 */
export function scaleToFitMaxEdge(
  width: number,
  height: number,
  maxEdge: number = IMAGE_MAX_EDGE_PX,
): { width: number; height: number } {
  const longest = Math.max(width, height)
  if (longest <= maxEdge || longest === 0) {
    return { width, height }
  }
  const ratio = maxEdge / longest
  return {
    width: Math.max(1, Math.round(width * ratio)),
    height: Math.max(1, Math.round(height * ratio)),
  }
}

/** データ URL から base64 部分だけを取り出す。 */
export function dataUrlToBase64(dataUrl: string): string {
  const comma = dataUrl.indexOf(',')
  return comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl
}

async function loadBitmap(file: File): Promise<ImageBitmap | HTMLImageElement> {
  if (typeof createImageBitmap === 'function') {
    return await createImageBitmap(file)
  }
  const url = URL.createObjectURL(file)
  try {
    return await new Promise<HTMLImageElement>((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = () => reject(new Error('画像を読み取れませんでした'))
      img.src = url
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * 画像を長辺 `IMAGE_MAX_EDGE_PX` まで縮小し、base64 の送信用ペイロードにする。
 *
 * 元ファイルが数 MB でも送信時は数百 KB に収まるため、JSON ボディのまま扱える。
 */
export async function downscaleImageAttachment(file: File): Promise<ChatAttachmentPayload> {
  const bitmap = await loadBitmap(file)
  const sourceWidth = 'width' in bitmap ? bitmap.width : 0
  const sourceHeight = 'height' in bitmap ? bitmap.height : 0
  const { width, height } = scaleToFitMaxEdge(sourceWidth, sourceHeight)

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    throw new Error('画像を変換できませんでした')
  }
  ctx.drawImage(bitmap as CanvasImageSource, 0, 0, width, height)
  if ('close' in bitmap && typeof bitmap.close === 'function') {
    bitmap.close()
  }

  // 縮小した時点で元形式を保つ意味は薄いので、常に JPEG に揃えて容量を抑える。
  // ただし元が PNG のまま等倍のときは透過を壊さないよう PNG を維持する。
  const keepPng =
    imageMediaTypeFor(file) === 'image/png' && width === sourceWidth && height === sourceHeight
  const mediaType = keepPng ? 'image/png' : 'image/jpeg'
  const dataUrl = canvas.toDataURL(mediaType, JPEG_QUALITY)
  return {
    kind: 'image',
    filename: file.name,
    media_type: mediaType,
    data_base64: dataUrlToBase64(dataUrl),
  }
}
