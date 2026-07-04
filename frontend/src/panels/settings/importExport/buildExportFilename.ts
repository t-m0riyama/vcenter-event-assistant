/**
 * 設定パネルの JSON エクスポート用ファイル名（`vea-*-YYYY-MM-DD.json`）を組み立てる。
 */
export function buildVeaExportFilename(prefix: string, date: Date = new Date()): string {
  return `${prefix}-${date.toISOString().slice(0, 10)}.json`
}
