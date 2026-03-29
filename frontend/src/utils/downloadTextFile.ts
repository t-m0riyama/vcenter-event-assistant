/**
 * ブラウザで UTF-8 テキストをファイルとしてダウンロードする（Markdown エクスポート等）。
 */
export function downloadTextFile(filename: string, content: string): void {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
